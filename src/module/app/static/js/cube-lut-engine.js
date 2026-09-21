(function(global){
'use strict';

var cubeCache = new Map();
var catalogCache = null;

function report(event, message, detail) {
  try {
    fetch('/api/client-log', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      keepalive: true,
      body: JSON.stringify({
        event: event || '',
        message: message || '',
        detail: detail || null,
        ua: navigator.userAgent || ''
      })
    }).catch(function(){});
  } catch (_) {}
}

function number3(parts, start) {
  return [
    Number.parseFloat(parts[start]),
    Number.parseFloat(parts[start + 1]),
    Number.parseFloat(parts[start + 2])
  ];
}

function parseCube(text, fallbackName) {
  var title = fallbackName || 'LUT';
  var size = 0;
  var domainMin = [0, 0, 0];
  var domainMax = [1, 1, 1];
  var values = [];
  var saw1D = false;
  var lines = String(text || '').replace(/^\uFEFF/, '').split(/\r?\n/);

  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].split('#', 1)[0].trim();
    if (!line) continue;
    var parts = line.split(/\s+/);
    var key = parts[0].toUpperCase();

    if (key === 'TITLE') {
      title = line.slice(parts[0].length).trim().replace(/^"|"$/g, '');
      continue;
    }
    if (key === 'LUT_1D_SIZE') {
      saw1D = true;
      continue;
    }
    if (key === 'LUT_3D_SIZE') {
      size = Number.parseInt(parts[1], 10);
      continue;
    }
    if (key === 'DOMAIN_MIN' && parts.length >= 4) {
      domainMin = number3(parts, 1);
      continue;
    }
    if (key === 'DOMAIN_MAX' && parts.length >= 4) {
      domainMax = number3(parts, 1);
      continue;
    }

    if (/^[+\-.0-9]/.test(parts[0]) && parts.length >= 3) {
      var rgb = number3(parts, 0);
      if (rgb.every(Number.isFinite)) {
        values.push(rgb[0], rgb[1], rgb[2]);
      }
    }
  }

  if (saw1D) throw new Error('1D LUTs are not accepted by the 3D LUT renderer');
  if (!Number.isInteger(size) || size < 2) throw new Error('Missing or invalid LUT_3D_SIZE');

  var expected = size * size * size;
  if (values.length !== expected * 3) {
    throw new Error('Invalid .cube data count: expected ' + expected + ' RGB rows, got ' + (values.length / 3));
  }

  for (var d = 0; d < 3; d++) {
    if (!Number.isFinite(domainMin[d]) || !Number.isFinite(domainMax[d]) || domainMax[d] <= domainMin[d]) {
      throw new Error('Invalid DOMAIN_MIN / DOMAIN_MAX');
    }
  }

  var rgba = new Float32Array(expected * 4);
  for (var p = 0, q = 0; p < values.length; p += 3, q += 4) {
    rgba[q] = values[p];
    rgba[q + 1] = values[p + 1];
    rgba[q + 2] = values[p + 2];
    rgba[q + 3] = 1;
  }

  return {
    title: title,
    size: size,
    domainMin: new Float32Array(domainMin),
    domainMax: new Float32Array(domainMax),
    rgba: rgba
  };
}

async function catalog(includeValidation) {
  if (!includeValidation && catalogCache) return catalogCache;
  var suffix = includeValidation ? '?include_validation=1' : '';
  var response = await fetch('/api/luts' + suffix, {cache: 'no-store'});
  if (!response.ok) throw new Error('LUT catalog HTTP ' + response.status);
  var data = await response.json();
  var items = Array.isArray(data.luts) ? data.luts : [];
  if (!includeValidation) catalogCache = items;
  return items;
}

async function loadCube(entry) {
  var name = typeof entry === 'string' ? entry : entry.name;
  if (!name) throw new Error('Missing LUT name');
  var sha = (entry && typeof entry === 'object' && entry.sha256) ? String(entry.sha256) : '';
  var cacheKey = name + (sha ? '@' + sha : '');
  if (cubeCache.has(cacheKey)) {
    report('lut-cache-hit', cacheKey);
    return cubeCache.get(cacheKey);
  }

  var t0 = performance.now();
  report('lut-fetch-start', cacheKey);
  var url = '/api/luts/' + encodeURIComponent(name) + (sha ? '?v=' + encodeURIComponent(sha) : '');
  var response = await fetch(url, {cache: 'default'});
  if (!response.ok) throw new Error('LUT HTTP ' + response.status + ': ' + name);
  var text = await response.text();
  var parseStart = performance.now();
  var cube = parseCube(text, name);
  cube.name = name;
  cube.interpolation = (
    entry && String(entry.interpolation || '').toLowerCase() === 'trilinear'
  ) ? 'trilinear' : 'tetrahedral';
  cube.meta = entry || {};
  cubeCache.set(cacheKey, cube);
  report('lut-loaded', cacheKey, {
    size: cube.size,
    fetch_ms: Math.round(parseStart - t0),
    parse_ms: Math.round(performance.now() - parseStart),
    bytes: text.length
  });
  return cube;
}

function compile(gl, type, source) {
  var shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    var log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error('WebGL shader compile failed: ' + log);
  }
  return shader;
}

function makeProgram(gl) {
  var vs = [
    '#version 300 es',
    'precision highp float;',
    'in vec2 aPosition;',
    'out vec2 vUV;',
    'void main(){',
    '  gl_Position=vec4(aPosition,0.0,1.0);',
    '  vUV=0.5*(aPosition+1.0);',
    '}'
  ].join('\n');

  var fs = [
    '#version 300 es',
    'precision highp float;',
    'precision highp sampler3D;',
    'in vec2 vUV;',
    'out vec4 outColor;',
    'uniform sampler2D uSource;',
    'uniform sampler3D uLut;',
    'uniform int uSize;',
    'uniform vec3 uDomainMin;',
    'uniform vec3 uDomainMax;',
    'uniform int uInterpolation;',
    'vec3 L(ivec3 p){ return texelFetch(uLut,p,0).rgb; }',
    'vec3 tri(vec3 x){',
    '  float n=float(uSize-1);',
    '  vec3 p=clamp(x,0.0,1.0)*n;',
    '  ivec3 a=ivec3(floor(p));',
    '  ivec3 b=min(a+ivec3(1),ivec3(uSize-1));',
    '  vec3 f=fract(p);',
    '  vec3 c00=mix(L(ivec3(a.x,a.y,a.z)),L(ivec3(b.x,a.y,a.z)),f.x);',
    '  vec3 c10=mix(L(ivec3(a.x,b.y,a.z)),L(ivec3(b.x,b.y,a.z)),f.x);',
    '  vec3 c01=mix(L(ivec3(a.x,a.y,b.z)),L(ivec3(b.x,a.y,b.z)),f.x);',
    '  vec3 c11=mix(L(ivec3(a.x,b.y,b.z)),L(ivec3(b.x,b.y,b.z)),f.x);',
    '  return mix(mix(c00,c10,f.y),mix(c01,c11,f.y),f.z);',
    '}',
    'vec3 tetra(vec3 x){',
    '  float n=float(uSize-1);',
    '  vec3 p=clamp(x,0.0,1.0)*n;',
    '  ivec3 a=ivec3(floor(p));',
    '  ivec3 b=min(a+ivec3(1),ivec3(uSize-1));',
    '  vec3 f=fract(p);',
    '  vec3 c000=L(ivec3(a.x,a.y,a.z));',
    '  vec3 c100=L(ivec3(b.x,a.y,a.z));',
    '  vec3 c010=L(ivec3(a.x,b.y,a.z));',
    '  vec3 c001=L(ivec3(a.x,a.y,b.z));',
    '  vec3 c110=L(ivec3(b.x,b.y,a.z));',
    '  vec3 c101=L(ivec3(b.x,a.y,b.z));',
    '  vec3 c011=L(ivec3(a.x,b.y,b.z));',
    '  vec3 c111=L(ivec3(b.x,b.y,b.z));',
    '  float r=f.r,g=f.g,bb=f.b;',
    '  if(r>=g){',
    '    if(g>=bb) return c000+r*(c100-c000)+g*(c110-c100)+bb*(c111-c110);',
    '    if(r>=bb) return c000+r*(c100-c000)+bb*(c101-c100)+g*(c111-c101);',
    '    return c000+bb*(c001-c000)+r*(c101-c001)+g*(c111-c101);',
    '  }',
    '  if(bb>=g) return c000+bb*(c001-c000)+g*(c011-c001)+r*(c111-c011);',
    '  if(bb>=r) return c000+g*(c010-c000)+bb*(c011-c010)+r*(c111-c011);',
    '  return c000+g*(c010-c000)+r*(c110-c010)+bb*(c111-c110);',
    '}',
    'void main(){',
    '  vec4 src=texture(uSource,vUV);',
    '  vec3 den=max(uDomainMax-uDomainMin,vec3(1e-12));',
    '  vec3 x=(src.rgb-uDomainMin)/den;',
    '  vec3 rgb=(uInterpolation==1)?tri(x):tetra(x);',
    '  outColor=vec4(rgb,src.a);',
    '}'
  ].join('\n');

  var program = gl.createProgram();
  var v = compile(gl, gl.VERTEX_SHADER, vs);
  var f = compile(gl, gl.FRAGMENT_SHADER, fs);
  gl.attachShader(program, v);
  gl.attachShader(program, f);
  gl.linkProgram(program);
  gl.deleteShader(v);
  gl.deleteShader(f);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    var log = gl.getProgramInfoLog(program);
    gl.deleteProgram(program);
    throw new Error('WebGL program link failed: ' + log);
  }
  return program;
}

function sourceDimensions(source) {
  if (source instanceof HTMLVideoElement) {
    return [source.videoWidth || 0, source.videoHeight || 0];
  }
  return [source.naturalWidth || 0, source.naturalHeight || 0];
}

function contentRect(source, host) {
  var sr = source.getBoundingClientRect();
  var hr = host.getBoundingClientRect();
  var dims = sourceDimensions(source);
  var sw = dims[0], sh = dims[1];
  if (!(sw > 0 && sh > 0 && sr.width > 0 && sr.height > 0)) {
    return {left: sr.left-hr.left, top: sr.top-hr.top, width: sr.width, height: sr.height};
  }
  var scale = Math.min(sr.width / sw, sr.height / sh);
  var w = sw * scale;
  var h = sh * scale;
  return {
    left: sr.left - hr.left + (sr.width - w) / 2,
    top: sr.top - hr.top + (sr.height - h) / 2,
    width: w,
    height: h
  };
}

function Renderer(source, host, options) {
  this.source = source;
  this.host = host || source.parentElement;
  this.options = options || {};
  this.sampleSource = this.options.sampleSource || source;
  this.canvas = document.createElement('canvas');
  this.canvas.className = 'cube-lut-canvas';
  this.canvas.hidden = true;
  this.canvas.style.position = 'absolute';
  this.canvas.style.pointerEvents = 'none';
  this.canvas.style.zIndex = String(this.options.zIndex || 4);
  this.host.appendChild(this.canvas);

  this.gl = null;
  this.program = null;
  this.srcTex = null;
  this.lutTex = null;
  this.vao = null;
  this.vertexBuffer = null;
  this.cube = null;
  this.active = false;
  this.raf = 0;
  this.firstFrame = false;
  this.contextLost = false;
  this.error = null;

  var self = this;
  this.canvas.addEventListener('webglcontextlost', function(ev){
    ev.preventDefault();
    self.contextLost = true;
    self._showSource();
    self._emitError('WebGL context lost; LUT disabled until context restore');
  });
  this.canvas.addEventListener('webglcontextrestored', function(){
    self.contextLost = false;
    try {
      self._initGL(true);
      if (self.cube) self._uploadLut(self.cube);
      if (self.active) self._start();
    } catch (e) {
      self._emitError(e.message || String(e));
    }
  });
}

Renderer.prototype._emitError = function(message) {
  this.error = message;
  report('lut-render-error', message, {
    source: this.source && this.source.tagName,
    readyState: this.source && this.source.readyState,
    naturalWidth: this.source && this.source.naturalWidth,
    naturalHeight: this.source && this.source.naturalHeight,
    videoWidth: this.source && this.source.videoWidth,
    videoHeight: this.source && this.source.videoHeight
  });
  try {
    this.source.dispatchEvent(new CustomEvent('cinepi-lut-error', {detail:{message:message}}));
  } catch (_) {}
};

Renderer.prototype._initGL = function(force) {
  if (this.gl && !force) return;
  var gl = this.canvas.getContext('webgl2', {
    alpha: false,
    antialias: false,
    premultipliedAlpha: false,
    preserveDrawingBuffer: false,
    powerPreference: 'high-performance'
  });
  if (!gl) throw new Error('WebGL2 unavailable; real 3D LUT cannot be applied');

  this.gl = gl;
  this.program = makeProgram(gl);
  report('webgl-init', 'ok', {
    version: gl.getParameter(gl.VERSION),
    shading: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
    max3d: gl.getParameter(gl.MAX_3D_TEXTURE_SIZE)
  });
  this.srcTex = gl.createTexture();
  this.lutTex = gl.createTexture();

  this.vao = gl.createVertexArray();
  this.vertexBuffer = gl.createBuffer();
  gl.bindVertexArray(this.vao);
  gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 3,-1, -1,3]), gl.STATIC_DRAW);
  var positionLocation = gl.getAttribLocation(this.program, 'aPosition');
  if (positionLocation < 0) throw new Error('WebGL position attribute unavailable');
  gl.enableVertexAttribArray(positionLocation);
  gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);
  gl.bindVertexArray(null);
  gl.bindBuffer(gl.ARRAY_BUFFER, null);

  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D, this.srcTex);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

  gl.activeTexture(gl.TEXTURE1);
  gl.bindTexture(gl.TEXTURE_3D, this.lutTex);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);

  gl.useProgram(this.program);
  gl.uniform1i(gl.getUniformLocation(this.program, 'uSource'), 0);
  gl.uniform1i(gl.getUniformLocation(this.program, 'uLut'), 1);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
  if (gl.UNPACK_COLORSPACE_CONVERSION_WEBGL !== undefined) {
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
  }
};

Renderer.prototype._uploadLut = function(cube) {
  var gl = this.gl;
  if (!gl) return;
  var max = gl.getParameter(gl.MAX_3D_TEXTURE_SIZE);

  /* UNPACK_FLIP_Y_WEBGL is for 2D image/video sources only. Leaving it set
     while uploading a 3D LUT reverses the flattened Y/depth rows and maps
     the white LUT corner to the red corner (verified by the GPU self-test). */
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  if (cube.size > max) {
    throw new Error('LUT size ' + cube.size + ' exceeds WebGL2 MAX_3D_TEXTURE_SIZE ' + max);
  }
  var packed = new Uint8Array(cube.rgba.length);
  for (var i = 0; i < cube.rgba.length; i += 4) {
    packed[i] = Math.max(0, Math.min(255, Math.round(cube.rgba[i] * 255)));
    packed[i + 1] = Math.max(0, Math.min(255, Math.round(cube.rgba[i + 1] * 255)));
    packed[i + 2] = Math.max(0, Math.min(255, Math.round(cube.rgba[i + 2] * 255)));
    packed[i + 3] = 255;
  }
  gl.activeTexture(gl.TEXTURE1);
  gl.bindTexture(gl.TEXTURE_3D, this.lutTex);
  gl.texImage3D(
    gl.TEXTURE_3D, 0, gl.RGBA8,
    cube.size, cube.size, cube.size,
    0, gl.RGBA, gl.UNSIGNED_BYTE, packed
  );
  var uploadError = gl.getError();
  if (uploadError !== gl.NO_ERROR) {
    throw new Error('3D LUT texture upload failed (0x' + uploadError.toString(16) + ')');
  }
  report('lut-uploaded', cube.name || cube.title || 'LUT', {
    size: cube.size,
    format: 'RGBA8',
    bytes: packed.byteLength
  });
};

Renderer.prototype._selfTest = function(cube) {
  var gl = this.gl;
  if (!gl || !cube) throw new Error('WebGL LUT self-test unavailable');

  this.canvas.width = 1;
  this.canvas.height = 1;
  gl.viewport(0, 0, 1, 1);
  gl.useProgram(this.program);

  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D, this.srcTex);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  gl.texImage2D(
    gl.TEXTURE_2D, 0, gl.RGBA,
    1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE,
    new Uint8Array([255,255,255,255])
  );

  gl.activeTexture(gl.TEXTURE1);
  gl.bindTexture(gl.TEXTURE_3D, this.lutTex);
  gl.uniform1i(gl.getUniformLocation(this.program, 'uSize'), cube.size);
  gl.uniform3fv(gl.getUniformLocation(this.program, 'uDomainMin'), cube.domainMin);
  gl.uniform3fv(gl.getUniformLocation(this.program, 'uDomainMax'), cube.domainMax);
  gl.uniform1i(
    gl.getUniformLocation(this.program, 'uInterpolation'),
    cube.interpolation === 'trilinear' ? 1 : 0
  );

  gl.bindVertexArray(this.vao);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
  gl.bindVertexArray(null);

  var pixel = new Uint8Array(4);
  gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
  var err = gl.getError();
  if (err !== gl.NO_ERROR) {
    throw new Error('WebGL LUT self-test failed (0x' + err.toString(16) + ')');
  }

  var i = cube.rgba.length - 4;
  var expected = [
    Math.max(0, Math.min(255, Math.round(cube.rgba[i] * 255))),
    Math.max(0, Math.min(255, Math.round(cube.rgba[i+1] * 255))),
    Math.max(0, Math.min(255, Math.round(cube.rgba[i+2] * 255)))
  ];
  var diff = Math.max(
    Math.abs(pixel[0]-expected[0]),
    Math.abs(pixel[1]-expected[1]),
    Math.abs(pixel[2]-expected[2])
  );
  report('lut-self-test', diff <= 4 ? 'pass' : 'mismatch', {
    got: [pixel[0],pixel[1],pixel[2]],
    expected: expected,
    max_diff: diff
  });
  if (diff > 4) {
    throw new Error(
      '3D LUT shader self-test mismatch: got '+
      pixel[0]+','+pixel[1]+','+pixel[2]+
      ' expected '+expected.join(',')
    );
  }
};

Renderer.prototype._syncGeometry = function() {
  var dims = sourceDimensions(this.sampleSource);
  if (!(dims[0] > 0 && dims[1] > 0)) return false;
  if (this.canvas.width !== dims[0] || this.canvas.height !== dims[1]) {
    this.canvas.width = dims[0];
    this.canvas.height = dims[1];
  }
  var r = contentRect(this.source, this.host);
  this.canvas.style.left = Math.round(r.left) + 'px';
  this.canvas.style.top = Math.round(r.top) + 'px';
  this.canvas.style.width = Math.max(1, Math.round(r.width)) + 'px';
  this.canvas.style.height = Math.max(1, Math.round(r.height)) + 'px';
  return r.width > 0 && r.height > 0;
};

Renderer.prototype._showSource = function() {
  this.source.style.opacity = '';
  this.canvas.hidden = true;
  this.firstFrame = false;
};

Renderer.prototype._showCanvas = function() {
  this.canvas.hidden = false;
  this.source.style.opacity = '0';
  if (!this.firstFrame) {
    var r = this.canvas.getBoundingClientRect();
    report('lut-first-frame', this.cube ? (this.cube.name || this.cube.title) : 'LUT', {
      canvas: [this.canvas.width, this.canvas.height],
      css: [Math.round(r.width), Math.round(r.height)],
      z: getComputedStyle(this.canvas).zIndex
    });
  }
  this.firstFrame = true;
};

Renderer.prototype._draw = function() {
  if (!this.active || !this.cube || this.contextLost) return;
  var gl = this.gl;
  if (!gl || !this._syncGeometry()) return;

  var dims = sourceDimensions(this.sampleSource);
  if (!(dims[0] > 0 && dims[1] > 0)) return;

  try {
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.useProgram(this.program);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.srcTex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, this.sampleSource);

    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_3D, this.lutTex);

    gl.uniform1i(gl.getUniformLocation(this.program, 'uSize'), this.cube.size);
    gl.uniform3fv(gl.getUniformLocation(this.program, 'uDomainMin'), this.cube.domainMin);
    gl.uniform3fv(gl.getUniformLocation(this.program, 'uDomainMax'), this.cube.domainMax);
    gl.uniform1i(
      gl.getUniformLocation(this.program, 'uInterpolation'),
      this.cube.interpolation === 'trilinear' ? 1 : 0
    );

    gl.bindVertexArray(this.vao);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindVertexArray(null);
    var glError = gl.getError();
    if (glError !== gl.NO_ERROR) {
      throw new Error('WebGL frame upload/draw failed (0x' + glError.toString(16) + ')');
    }
    if (!this.firstFrame) this._showCanvas();
  } catch (e) {
    this.active = false;
    this._showSource();
    this._emitError(
      'Exact 3D LUT rendering failed: ' + (e && e.message ? e.message : String(e))
    );
  }
};

Renderer.prototype._loop = function() {
  var self = this;
  if (!this.active) return;
  this._draw();
  this.raf = requestAnimationFrame(function(){ self._loop(); });
};

Renderer.prototype._start = function() {
  cancelAnimationFrame(this.raf);
  this._loop();
};

Renderer.prototype.setLut = async function(entry) {
  if (!entry || !entry.name) {
    this.disable();
    return;
  }
  report('lut-set-start', entry.name);
  this._initGL(false);
  var cube = await loadCube(entry);
  this.cube = cube;
  this._uploadLut(cube);
  this._selfTest(cube);
  this.active = true;
  this.error = null;
  report('lut-set-active', entry.name);
  this._start();
};

Renderer.prototype.disable = function() {
  this.active = false;
  cancelAnimationFrame(this.raf);
  this.cube = null;
  this._showSource();
};

Renderer.prototype.destroy = function() {
  this.disable();
  if (this.canvas && this.canvas.parentNode) this.canvas.parentNode.removeChild(this.canvas);
};

async function populateSelect(select, label) {
  if (!select) return [];
  var items = await catalog(false);
  while (select.options.length) select.remove(0);

  var none = document.createElement('option');
  none.value = '';
  none.textContent = (label || 'LOOK') + ': none';
  select.appendChild(none);

  if (!items.length) {
    var empty = document.createElement('option');
    empty.value = '__none_installed__';
    empty.disabled = true;
    empty.textContent = 'No real .cube LUT installed';
    select.appendChild(empty);
    return items;
  }

  items.forEach(function(item){
    var option = document.createElement('option');
    option.value = item.name;
    option.textContent = item.display_name + (item.verified ? '' : ' [unverified source]');
    option.dataset.inputSpace = item.input_space || '';
    option.dataset.outputSpace = item.output_space || '';
    select.appendChild(option);
  });
  return items;
}

global.CinePiCubeLUT = {
  parseCube: parseCube,
  catalog: catalog,
  loadCube: loadCube,
  populateSelect: populateSelect,
  Renderer: Renderer
};
})(window);
