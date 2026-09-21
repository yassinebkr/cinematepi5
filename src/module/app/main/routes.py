from flask import Blueprint, current_app, jsonify, request, render_template
from module.redis_controller import ParameterKey

main_routes = Blueprint('main', __name__)

@main_routes.route('/sw.js')
def service_worker():
    response = current_app.send_static_file('sw.js')
    response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response

@main_routes.route('/')
def index():
    redis_controller = current_app.config['REDIS_CONTROLLER']
    cinepi_controller = current_app.config['CINEPI_CONTROLLER']
    simple_gui = current_app.config['SIMPLE_GUI']
    sensor_detect = current_app.config['SENSOR_DETECT']

    iso_value = redis_controller.get_value(ParameterKey.ISO.value)
    shutter_a_value = redis_controller.get_value(ParameterKey.SHUTTER_A.value)
    fps_value = redis_controller.get_value(ParameterKey.FPS_ACTUAL.value)
    wb_value = redis_controller.get_value(ParameterKey.WB_USER.value)
    background_color_value = simple_gui.get_background_color()
    
    dynamic_data = simple_gui.populate_values()

    dynamic_data = {
        "iso": iso_value if iso_value else "Initializing...",
        "shutter_a": shutter_a_value if shutter_a_value else "Initializing...",
        "fps": fps_value if fps_value else "Initializing...",
        "background_color": background_color_value if background_color_value else "Initializing...",
    }

    # Use the same host the browser used to reach CineMate. This avoids an
    # unnecessary dependency on mDNS when a phone/tablet connects by IP.
    stream_host = request.host.split(':', 1)[0]
    stream_url = f"http://{stream_host}:8000/stream"

    return render_template('template.html', stream_url=stream_url, 
                           dynamic_data=dynamic_data,
                           iso_values=cinepi_controller.iso_steps, 
                           shutter_speed_values=cinepi_controller.shutter_a_steps_dynamic,
                           fps_values=cinepi_controller.fps_steps_dynamic,
                           wb_steps=cinepi_controller.wb_steps,
                           current_wb=wb_value,
                           resolution_values=sensor_detect.get_available_resolutions(),
                           current_iso=iso_value,
                           current_shutter_a=shutter_a_value,
                           current_fps=fps_value,
                           background_color=background_color_value)


# ---- Real .cube 3D LUT catalog ----------------------------------------
import hashlib as _hashlib

_LUT_DIR = '/home/pi/cinemate/luts'

def _lut_safe_name(name):
    if not isinstance(name, str):
        return None
    base = _os.path.basename(name)
    if base != name or not base.lower().endswith('.cube'):
        return None
    return base

def _lut_header(path):
    title = None
    size = None
    domain_min = [0.0, 0.0, 0.0]
    domain_max = [1.0, 1.0, 1.0]
    is_1d = False
    try:
        with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
            for _ in range(256):
                line = f.readline()
                if not line:
                    break
                line = line.split('#', 1)[0].strip()
                if not line:
                    continue
                parts = line.split()
                key = parts[0].upper()
                if key == 'TITLE':
                    title = line[len(parts[0]):].strip().strip('"')
                elif key == 'LUT_3D_SIZE' and len(parts) >= 2:
                    size = int(parts[1])
                elif key == 'LUT_1D_SIZE':
                    is_1d = True
                elif key == 'DOMAIN_MIN' and len(parts) >= 4:
                    domain_min = [float(x) for x in parts[1:4]]
                elif key == 'DOMAIN_MAX' and len(parts) >= 4:
                    domain_max = [float(x) for x in parts[1:4]]
                elif size is not None and parts and parts[0][0] in '+-.0123456789':
                    break
    except Exception:
        return None
    if is_1d or not size or size < 2:
        return None
    return {
        'title': title,
        'size': size,
        'domain_min': domain_min,
        'domain_max': domain_max,
    }

@main_routes.route('/api/luts')
def lut_catalog():
    _os.makedirs(_LUT_DIR, exist_ok=True)
    include_validation = request.args.get('include_validation') == '1'
    items = []
    for path in sorted(_glob.glob(_os.path.join(_LUT_DIR, '*.cube'))):
        name = _os.path.basename(path)
        if name.startswith('_') and not include_validation:
            continue
        hdr = _lut_header(path)
        if not hdr:
            continue
        sidecar = _os.path.splitext(path)[0] + '.json'
        meta = {}
        if _os.path.isfile(sidecar):
            try:
                with open(sidecar, 'r', encoding='utf-8') as f:
                    meta = _json.load(f)
            except Exception:
                meta = {}
        try:
            with open(path, 'rb') as f:
                sha256 = _hashlib.sha256(f.read()).hexdigest()
        except Exception:
            sha256 = None
        interpolation = str(meta.get('interpolation', 'tetrahedral')).lower()
        if interpolation not in ('tetrahedral', 'trilinear'):
            interpolation = 'tetrahedral'
        items.append({
            'name': name,
            'display_name': meta.get('display_name') or hdr.get('title') or _os.path.splitext(name)[0],
            'size': hdr['size'],
            'domain_min': hdr['domain_min'],
            'domain_max': hdr['domain_max'],
            'interpolation': interpolation,
            'source': meta.get('source'),
            'source_url': meta.get('source_url'),
            'input_space': meta.get('input_space'),
            'output_space': meta.get('output_space'),
            'category': meta.get('category'),
            'recommended_mix_percent': meta.get('recommended_mix_percent'),
            'official_cinepi': bool(meta.get('official_cinepi', False)),
            'redistributable_by_cinepi': bool(meta.get('redistributable_by_cinepi', False)),
            'release_license': meta.get('release_license'),
            'description': meta.get('description'),
            'verified': bool(meta.get('verified', False)),
            'sha256': sha256,
        })
    return jsonify(luts=items)

@main_routes.route('/api/luts/official-pack.zip')
def official_lut_pack():
    path = _os.path.join(_LUT_DIR, 'cinepi-official-lut-pack.zip')
    if not _os.path.isfile(path):
        abort(404)
    return send_file(
        path,
        mimetype='application/zip',
        as_attachment=True,
        download_name='cinepi-official-lut-pack.zip',
        conditional=True
    )


@main_routes.route('/api/luts/<name>')
def lut_file(name):
    safe = _lut_safe_name(name)
    if not safe:
        abort(404)
    path = _os.path.join(_LUT_DIR, safe)
    if not _os.path.isfile(path):
        abort(404)

    # .cube files are extremely repetitive text. Safari on a phone should not
    # have to pull ~1 MB every time the user selects a look. Compress at the
    # HTTP layer; fetch() transparently returns the original text.
    if 'gzip' in request.headers.get('Accept-Encoding', '').lower():
        import gzip as _gzip
        from flask import Response
        with open(path, 'rb') as f:
            raw = f.read()
        payload = _gzip.compress(raw, compresslevel=5)
        response = Response(payload, mimetype='text/plain')
        response.headers['Content-Encoding'] = 'gzip'
        response.headers['Content-Length'] = str(len(payload))
        response.headers['Vary'] = 'Accept-Encoding'
        response.headers['ETag'] = '"' + _hashlib.sha256(raw).hexdigest() + '"'
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response

    response = send_file(path, mimetype='text/plain', conditional=True)
    response.headers['Cache-Control'] = 'public, max-age=86400'
    response.headers['Vary'] = 'Accept-Encoding'
    return response


@main_routes.route('/api/client-log', methods=['POST', 'GET'])
def client_log():
    # Small local diagnostic channel for the camera UI. It deliberately logs
    # renderer state/errors only, never frames or media.
    import json as _client_json, time as _client_time
    path = '/tmp/cinemate-client.log'
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        allowed = {
            'event': str(data.get('event', ''))[:80],
            'message': str(data.get('message', ''))[:500],
            'detail': data.get('detail'),
            'ua': str(data.get('ua', ''))[:300],
            'ts': _client_time.time(),
        }
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(_client_json.dumps(allowed, ensure_ascii=False, default=str) + '\n')
        except Exception:
            pass
        return jsonify(ok=True)
    try:
        lines = open(path, 'r', encoding='utf-8', errors='replace').read().splitlines()[-120:]
    except Exception:
        lines = []
    return jsonify(lines=lines)

# ---- Clips / proxy playback -------------------------------------------
import os as _os, glob as _glob
from flask import send_file, abort

_RAW = '/media/RAW'

import json as _json, struct as _struct

def _dng_meta(path):
    with open(path,'rb') as f:
        hdr=f.read(8)
        if hdr[:4]!=b'II*\x00': raise ValueError
        off=_struct.unpack('<I',hdr[4:8])[0]
        f.seek(off)
        data=f.read(6+12*512)
        n=_struct.unpack('<H',data[:2])[0]
        w=h=0; fps=0.0; fpsoff=None
        for i in range(n):
            e=2+12*i
            tag,typ,cnt,val=_struct.unpack('<HHII',data[e:e+12])
            if tag==256: w=val
            elif tag==257: h=val
            elif tag==0xC764: fpsoff=val
        if fpsoff:
            f.seek(fpsoff)
            nu,de=_struct.unpack('<ii',f.read(8))
            if de: fps=nu/de
    return w,h,fps

def _clip_meta(d, frames):
    mp=d+'.meta.json'
    try:
        m=_json.load(open(mp))
        if m.get('frames')==frames and 'drops' in m: return m
    except Exception: pass
    m={'frames':frames}
    try:
        dngs=sorted(_glob.glob(d+'*.dng'))
        w,h,fps=_dng_meta(dngs[0])
        m.update({'w':w,'h':h,'fps':round(fps,3)})
        if fps: m['dur']=round(frames/fps,1)
        idx=[]
        for f in dngs:
            try: idx.append(int(f[-13:-4]))
            except Exception: pass
        if idx:
            idx.sort()
            span=idx[-1]-idx[0]+1
            m['drops']=max(0,span-len(idx))
            if fps: m['dur']=round(span/fps,1)
    except Exception: pass
    try: _json.dump(m,open(mp,'w'))
    except Exception: pass
    return m

@main_routes.route('/recording-state')
@main_routes.route('/clips/recording-state')
def clips_recording_state():
    rc = current_app.config['REDIS_CONTROLLER']

    def _on(key):
        return str(rc.get_value(key, '0') or '0').strip().lower() in (
            '1', 'true', 'yes', 'on'
        )

    recording = _on(ParameterKey.IS_RECORDING.value)
    writing = _on(ParameterKey.IS_WRITING.value)
    writing_buf = _on(ParameterKey.IS_WRITING_BUF.value)
    buffering = _on(ParameterKey.IS_BUFFERING.value)

    return jsonify(
        recording=recording,
        writing=writing,
        writing_buf=writing_buf,
        buffering=buffering,
        finalized=(not recording and not writing and not writing_buf and not buffering),
        recording_time=rc.get_value(ParameterKey.RECORDING_TIME.value, '0'),
        timecode=rc.get_value(ParameterKey.RECORDING_TC_REC.value, '00:00:00:00'),
        framecount=rc.get_value(ParameterKey.FRAMECOUNT.value, '0'),
    )


@main_routes.route('/clips')
def clips():
    items = []
    for d in sorted(_glob.glob(_RAW+'/CINEPI_*/'), key=lambda x: _os.path.basename(x.rstrip('/')), reverse=True):
        name = _os.path.basename(d.rstrip('/'))
        frames = len(_glob.glob(d+'*.dng'))
        if frames == 0:
            continue
        m=_clip_meta(d, frames)
        if m.get('w'):
            label='%dx%d | %gfps | %.1fs | %dfr'%(m['w'],m['h'],m.get('fps',0),m.get('dur',0),frames)
            dr=m.get('drops')
            if dr is not None:
                label+=(' | 0 drops' if dr==0 else ' | %d DROPS'%dr)
        else:
            label='%d frames'%frames
        shot={}
        try: shot=_json.load(open(d+'shot.json'))
        except Exception: pass
        items.append({'name': name, 'frames': frames, 'label': label, 'shot': shot,
                      'proxy': _os.path.exists(d+'proxy.mp4'),
                      'thumb': _os.path.exists(d+'thumb.jpg')})
    return render_template('clips.html', clips=items)

@main_routes.route('/clips/<name>/thumb.jpg')
def clip_thumb(name):
    if '/' in name or '..' in name: abort(404)
    p=_os.path.join(_RAW,name,'thumb.jpg')
    if not _os.path.exists(p): abort(404)
    return send_file(p, mimetype='image/jpeg', conditional=True)

@main_routes.route('/clips/<name>/proxy.mp4')
def clip_proxy(name):
    if '/' in name or '..' in name:
        abort(404)
    p = _os.path.join(_RAW, name, 'proxy.mp4')
    if not _os.path.exists(p):
        abort(404)
    try:
        _os.utime(p, None)  # mark as recently watched (prune protection)
    except OSError:
        pass
    return send_file(p, mimetype='video/mp4', conditional=True)

_REQ = '/media/RAW/.proxy_requests'

@main_routes.route('/clips/<name>/render', methods=['POST'])
def clip_render(name):
    if '/' in name or '..' in name:
        abort(404)
    if not _os.path.isdir(_os.path.join(_RAW, name)):
        abort(404)
    _os.makedirs(_REQ, exist_ok=True)
    disabled = _os.path.join(_RAW, name, '.proxy_disabled')
    try:
        _os.remove(disabled)
    except OSError:
        pass
    open(_os.path.join(_REQ, name), 'a').close()
    return jsonify({'queued': True})

import time as _time, shutil as _shutil, subprocess as _subprocess

@main_routes.route('/clips/<name>/proxy/delete', methods=['POST'])
def clip_proxy_delete(name):
    if '/' in name or '..' in name or not name.startswith('CINEPI_'):
        abort(404)
    d = _os.path.join(_RAW, name)
    if not _os.path.isdir(d):
        abort(404)
    if _rec_now():
        return jsonify({'ok': False, 'error': 'recording in progress'}), 409

    active = False
    try:
        with open('/tmp/proxygen_status.json') as f:
            st = _json.load(f)
        active = (
            st.get('clip') == name and
            st.get('state') in ('preparing','encoding','paused','verifying')
        )
    except Exception:
        active = False
    if active:
        return jsonify({'ok': False, 'error': 'proxy encoding in progress'}), 409

    try:
        _os.remove(_os.path.join(_REQ, name))
    except OSError:
        pass
    try:
        _os.remove(_os.path.join(d, '.proxy.tmp.mp4'))
    except OSError:
        pass

    proxy = _os.path.join(d, 'proxy.mp4')
    existed = _os.path.isfile(proxy)
    if existed:
        _os.remove(proxy)

    # Persist the operator's choice. Auto-render skips this marker; an explicit
    # click on the clip removes it again in clip_render().
    open(_os.path.join(d, '.proxy_disabled'), 'a').close()
    return jsonify({'ok': True, 'deleted': existed, 'raw_preserved': True})

@main_routes.route('/clips/<name>/delete', methods=['POST'])
def clip_delete(name):
    if '/' in name or '..' in name or not name.startswith('CINEPI_'):
        abort(404)
    d = _os.path.join(_RAW, name)
    if not _os.path.isdir(d):
        abort(404)
    try:
        rec = _subprocess.run(['redis-cli','get','is_recording'],
                              capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        rec = '1'
    if rec == '1':
        return jsonify({'ok': False, 'error': 'recording in progress'}), 409
    trash = _os.path.join(_RAW, '.trash')
    _os.makedirs(trash, exist_ok=True)
    dst = _os.path.join(trash, name)
    if _os.path.exists(dst):
        dst += '.%d' % int(_time.time())
    _os.rename(d, dst)
    # drop any pending render request
    try:
        _os.remove(_os.path.join(_REQ, name))
    except OSError:
        pass
    return jsonify({'ok': True})

_TRASH = '/media/RAW/.trash'

def _rec_now():
    try:
        return _subprocess.run(['redis-cli','get','is_recording'],
                               capture_output=True, text=True, timeout=3).stdout.strip() == '1'
    except Exception:
        return True

@main_routes.route('/trash')
def trash_list():
    items = []
    if _os.path.isdir(_TRASH):
        for d in sorted(_os.listdir(_TRASH), reverse=True):
            p = _os.path.join(_TRASH, d)
            if _os.path.isdir(p):
                items.append({'name': d, 'files': len(_os.listdir(p))})
    return jsonify(items)

@main_routes.route('/trash/delete', methods=['POST'])
def trash_delete():
    if _rec_now():
        return jsonify({'ok': False, 'error': 'recording in progress'}), 409
    names = (request.get_json(silent=True) or {}).get('names', [])
    deleted = []
    for n in names:
        if '/' in n or '..' in n or not n.startswith('CINEPI_'):
            continue
        p = _os.path.join(_TRASH, n)
        if _os.path.isdir(p):
            _shutil.rmtree(p)
            deleted.append(n)
    return jsonify({'ok': True, 'deleted': deleted})

_BREQ = '/media/RAW/.backup_requests'
_BSTATUS = '/run/backup_status.json'

@main_routes.route('/backup')
def backup_page():
    items=[]
    for d in sorted(_glob.glob(_RAW+'/CINEPI_*/'), key=lambda x: _os.path.basename(x.rstrip('/')), reverse=True):
        name=_os.path.basename(d.rstrip('/'))
        frames=len(_glob.glob(d+'*.dng'))
        if frames==0: continue
        sz=0
        try:
            f0=sorted(_glob.glob(d+'*.dng'))[0]
            sz=_os.path.getsize(f0)*frames
        except Exception: pass
        items.append({'name':name,'frames':frames,'gb':round(sz/1e9,2),
                      'backed':_os.path.exists(d+'.backup_ok'),
                      'queued':_os.path.exists(_os.path.join(_BREQ,name))})
    return render_template('backup.html', clips=items)

@main_routes.route('/backup/status')
def backup_status():
    st={}
    try: st=_json.load(open(_BSTATUS))
    except Exception: st={'state':'daemon not running'}
    return jsonify(st)

@main_routes.route('/backup/clips.json')
def backup_clips_json():
    items=[]
    for d in sorted(_glob.glob(_RAW+'/CINEPI_*/'), key=lambda x: _os.path.basename(x.rstrip('/')), reverse=True):
        name=_os.path.basename(d.rstrip('/'))
        if not _glob.glob(d+'*.dng'): continue
        items.append({'name':name,
                      'backed':_os.path.exists(d+'.backup_ok'),
                      'queued':_os.path.exists(_os.path.join(_BREQ,name))})
    return jsonify(items)

@main_routes.route('/backup/cancel', methods=['POST'])
def backup_cancel():
    _os.makedirs(_BREQ, exist_ok=True)
    open(_os.path.join(_BREQ,'.cancel'),'a').close()
    # also clear pending queue markers immediately
    for f in _glob.glob(_os.path.join(_BREQ,'CINEPI_*')):
        try: _os.remove(f)
        except OSError: pass
    return jsonify({'ok': True})

@main_routes.route('/backup/start', methods=['POST'])
def backup_start():
    names=(request.get_json(silent=True) or {}).get('names',[])
    _os.makedirs(_BREQ, exist_ok=True)
    n=0
    for nm in names:
        if '/' in nm or '..' in nm or not nm.startswith('CINEPI_'): continue
        if not _os.path.isdir(_os.path.join(_RAW,nm)): continue
        open(_os.path.join(_BREQ,nm),'a').close(); n+=1
    return jsonify({'ok':True,'queued':n})

_PSTATUS = '/tmp/proxygen_status.json'

@main_routes.route('/clips/<name>/status')
def clip_status(name):
    if '/' in name or '..' in name:
        abort(404)
    d = _os.path.join(_RAW, name)
    ready = _os.path.exists(_os.path.join(d, 'proxy.mp4'))

    st = {}
    try:
        with open(_PSTATUS) as f:
            st = _json.load(f)
    except Exception:
        st = {}

    queued_path = _os.path.join(_REQ, name)
    queued = _os.path.exists(queued_path)
    suppressed = _os.path.exists(_os.path.join(d, '.proxy_disabled'))
    active = st.get('clip') == name and st.get('state') in (
        'preparing', 'encoding', 'paused', 'verifying'
    )

    queue_position = 0
    if queued and not active:
        try:
            reqs = [
                x for x in _glob.glob(_os.path.join(_REQ, '*'))
                if _os.path.isfile(x) and not _os.path.basename(x).startswith('.')
            ]
            reqs.sort(key=_os.path.getmtime)
            names = [_os.path.basename(x) for x in reqs]
            if name in names:
                queue_position = names.index(name) + 1
        except Exception:
            queue_position = 0

    if ready:
        state = 'ready'
        frame = total = 0
        try:
            total = len(_glob.glob(_os.path.join(d, '*.dng')))
            frame = total
        except Exception:
            pass
        percent = 100.0
        paused = False
        message = 'proxy ready'
    elif active:
        state = st.get('state', 'encoding')
        frame = int(st.get('frame') or 0)
        total = int(st.get('total') or 0)
        percent = float(st.get('percent') or 0.0)
        paused = bool(st.get('paused'))
        message = st.get('message') or state
    elif queued:
        state = 'queued'
        frame = 0
        total = len(_glob.glob(_os.path.join(d, '*.dng')))
        percent = 0.0
        paused = False
        message = (
            'queued'
            if not queue_position
            else 'queued (%d ahead)' % max(0, queue_position - 1)
        )
    elif suppressed:
        state = 'disabled'
        frame = 0
        total = len(_glob.glob(_os.path.join(d, '*.dng')))
        percent = 0.0
        paused = False
        message = 'proxy deleted; tap clip to regenerate'
    elif st.get('clip') == name and st.get('state') == 'error':
        state = 'error'
        frame = int(st.get('frame') or 0)
        total = int(st.get('total') or 0)
        percent = float(st.get('percent') or 0.0)
        paused = False
        message = st.get('message') or 'proxy encoding failed'
    else:
        state = 'idle'
        frame = 0
        total = len(_glob.glob(_os.path.join(d, '*.dng')))
        percent = 0.0
        paused = False
        message = 'no proxy'

    return jsonify({
        'ready': ready,
        'rendering': bool(active or queued or _os.path.exists(_os.path.join(d, '.proxy.tmp.mp4'))),
        'state': state,
        'frame': frame,
        'total': total,
        'percent': round(max(0.0, min(100.0, percent)), 1),
        'paused': paused,
        'message': message,
        'queue_position': queue_position,
        'suppressed': suppressed,
    })


@main_routes.route('/backup/auto', methods=['GET','POST'])
def backup_auto():
    p='/media/RAW/.backup_requests/.auto_disabled'
    if request.method=='POST':
        on=bool((request.get_json(silent=True) or {}).get('on'))
        try:
            if on:
                if _os.path.exists(p): _os.remove(p)
            else:
                open(p,'w').close()
        except Exception as e:
            return jsonify(error=str(e)),500
    return jsonify(on=not _os.path.exists(p))


_frame_cache={'jpg':None,'ts':0.0,'want':0.0}
def _frame_reader():
    import urllib.request
    while True:
        if _time.time()-_frame_cache['want']>10:
            _time.sleep(0.5); continue
        try:
            rq=urllib.request.urlopen('http://127.0.0.1:8000/stream',timeout=5)
            buf=b''
            while _time.time()-_frame_cache['want']<=10:
                c=rq.read(4096)
                if not c: break
                buf+=c
                st=buf.find(b'\xff\xd8')
                en=buf.find(b'\xff\xd9',st+2) if st!=-1 else -1
                if st!=-1 and en!=-1:
                    _frame_cache['jpg']=buf[st:en+2]; _frame_cache['ts']=_time.time()
                    buf=buf[en+2:]
                if len(buf)>3000000: buf=b''
            try: rq.close()
            except Exception: pass
        except Exception:
            _time.sleep(2)
import threading as _threading
_threading.Thread(target=_frame_reader,daemon=True).start()

@main_routes.route('/frame.jpg')
def frame_jpg():
    from flask import Response
    _frame_cache['want']=_time.time()
    if _frame_cache['jpg'] and _time.time()-_frame_cache['ts']<10:
        return Response(_frame_cache['jpg'],mimetype='image/jpeg',headers={'Cache-Control':'no-store'})
    return ('',503)


@main_routes.route('/power.json')
def power_json():
    w=0.0
    try:
        out=_subprocess.run(['vcgencmd','pmic_read_adc'],capture_output=True,text=True,timeout=3).stdout
        V={};A={}
        import re as _re
        for ln in out.splitlines():
            mm=_re.match(r'\s*(\S+?)_(V|A)\s+\w+\(\d+\)=([0-9.]+)',ln)
            if mm:
                (V if mm.group(2)=='V' else A)[mm.group(1)]=float(mm.group(3))
        w=sum(V.get(k,0)*A[k] for k in A)*1.18
    except Exception:
        pass
    return jsonify(watts=round(w,2))

@main_routes.route('/shutdown', methods=['POST'])
def shutdown():
    def later():
        _time.sleep(1)
        _subprocess.run(['sudo','shutdown','-h','now'])
    _threading.Thread(target=later,daemon=True).start()
    return jsonify(ok=True)


@main_routes.route('/clips/<name>/meta', methods=['GET','POST'])
def clip_shot_meta(name):
    if '/' in name or '..' in name or not name.startswith('CINEPI_'): abort(404)
    sp=_os.path.join(_RAW,name,'shot.json')
    if request.method=='POST':
        j=request.get_json(silent=True) or {}
        try:
            data={'scene':str(j.get('scene',''))[:32],'take':int(j.get('take',0) or 0),
                  'note':str(j.get('note',''))[:500],'rating':max(0,min(5,int(j.get('rating',0) or 0)))}
            _json.dump(data,open(sp,'w'))
        except Exception as e:
            return jsonify(error=str(e)),500
        return jsonify(ok=True)
    try:
        return jsonify(**_json.load(open(sp)))
    except Exception:
        return jsonify(scene='',take=0,note='',rating=0)


@main_routes.route('/shotmeta', methods=['GET','POST'])
def shotmeta():
    sp=_RAW+'/.shotmeta.json'
    if request.method=='POST':
        j=request.get_json(silent=True) or {}
        try:
            data={'auto':bool(j.get('auto',True)),'project':str(j.get('project',''))[:64],
                  'scene':str(j.get('scene',''))[:32],
                  'scenes':[str(x)[:32] for x in (j.get('scenes') or [])][:50]}
            _json.dump(data,open(sp,'w'))
        except Exception as e:
            return jsonify(error=str(e)),500
        return jsonify(ok=True)
    try:
        return jsonify(**_json.load(open(sp)))
    except Exception:
        return jsonify(auto=True,project='',scene='',scenes=[])


@main_routes.route('/imu-calibration', methods=['GET', 'POST'])
def imu_calibration():
    import json as _json
    import redis as _redis

    ctrl = current_app.config.get('CINEPI_CONTROLLER')
    rc = _redis.Redis()

    def _status():
        try:
            raw = rc.get('imu_cal_status')
            if not raw:
                return {}
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode()
            value = _json.loads(raw)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    if request.method == 'GET':
        st = _status()
        active = (rc.get('imu_cal_active') or b'0').decode() == '1'
        return jsonify(ok=True, active=active, status=st)

    if ctrl is None:
        return jsonify(ok=False, error='controller unavailable'), 500

    data = request.get_json(silent=True) or {}
    action = str(data.get('action') or 'start').strip().lower()

    try:
        if action == 'start':
            ok = bool(ctrl.start_imu_calibration())
            return jsonify(ok=ok, active=ctrl._imu_cal_active(), status=ctrl._imu_cal_status())

        if action == 'cancel':
            ctrl._finish_imu_calibration(save=False)
            return jsonify(ok=True, active=False, status=ctrl._imu_cal_status())

        if action == 'confirm':
            handled = bool(ctrl._imu_cal_input('confirm'))
            return jsonify(ok=handled, active=ctrl._imu_cal_active(), status=ctrl._imu_cal_status())

        if action == 'next':
            handled = bool(ctrl._imu_cal_input('next'))
            return jsonify(ok=handled, active=ctrl._imu_cal_active(), status=ctrl._imu_cal_status())

        if action == 'prev':
            handled = bool(ctrl._imu_cal_input('prev'))
            return jsonify(ok=handled, active=ctrl._imu_cal_active(), status=ctrl._imu_cal_status())

        return jsonify(ok=False, error='unknown action'), 400
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500



@main_routes.route('/darkcal', methods=['POST'])
def darkcal():
    import glob as _g
    ctrl=current_app.config.get('CINEPI_CONTROLLER')
    if ctrl is None:
        return jsonify(ok=False,error='controller unavailable'),500
    before=set(_g.glob('/media/RAW/CINEPI_*/'))
    _subprocess.run(['sudo','systemctl','stop','dng-recompress'])
    try:
        ctrl.rec()
        _time.sleep(1.6)
        ctrl.rec()
        d=None
        for _ in range(20):
            _time.sleep(1)
            new=set(_g.glob('/media/RAW/CINEPI_*/'))-before
            if new: d=sorted(new)[-1]; break
        if not d:
            return jsonify(ok=False,error='no clip captured'),500
        _time.sleep(2)
        out=_subprocess.run(['/home/pi/.cinemate-env/bin/python3','/home/pi/darkcal/darkcal.py','--analyze',d],
                            capture_output=True,text=True,timeout=120)
        line=out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ''
        try:
            return jsonify(**_json.loads(line))
        except Exception:
            return jsonify(ok=False,error=(out.stderr or out.stdout)[-400:]),500
    except Exception as e:
        return jsonify(ok=False,error=str(e)),500
    finally:
        _subprocess.run(['sudo','systemctl','start','dng-recompress'])


@main_routes.route('/imu.json')
def imu_json():
    try:
        import redis as _redis
        _rc=_redis.Redis()
        v=lambda k: float((_rc.get(k) or b'0').decode() or 0)
        b=lambda k: (_rc.get(k) or b'0').decode() == '1'
        return jsonify(
            roll=v('imu_roll'),
            pitch=v('imu_pitch'),
            shake=v('imu_shake'),
            temperature_c=v('imu_temp_c'),
            calibrated=b('imu_calibrated'),
        )
    except Exception as e:
        return jsonify(error=str(e)),500


@main_routes.route('/hud', methods=['GET','POST'])
def hud():
    try:
        from flask import request as _rq
        import redis as _redis
        _rc=_redis.Redis()
        if _rq.method=='POST':
            j=_rq.get_json(force=True) or {}
            if 'hdmi' in j: _rc.set('hud_level','1' if j.get('hdmi') else '0')
            try: open('/home/pi/.hud_pref','w').write('1' if j.get('hdmi') else '0')
            except Exception: pass
        return jsonify(hdmi=(_rc.get('hud_level') or b'0').decode()=='1')
    except Exception as e:
        return jsonify(error=str(e)),500

@main_routes.route('/levelcal', methods=['POST'])
def levelcal():
    """Set the operator horizon without overwriting physical IMU calibration."""
    try:
        import os as _os
        import redis as _redis
        _rc=_redis.Redis()
        g=lambda k: float((_rc.get(k) or b'0').decode() or 0)
        calibrated=(_rc.get('imu_calibrated') or b'0').decode()=='1'

        if calibrated:
            cp='/home/pi/gyrologd/level_zero.json'
            zero={'roll':g('level_zero_roll'),'pitch':g('level_zero_pitch')}
            zero={
                'roll':round(zero['roll']+g('imu_roll'),4),
                'pitch':round(zero['pitch']+g('imu_pitch'),4),
            }
            tmp=cp+'.tmp'
            with open(tmp,'w') as f:
                f.write(_json.dumps(zero,indent=2,sort_keys=True))
                f.flush()
                _os.fsync(f.fileno())
            _os.replace(tmp,cp)
            _rc.mset({
                'level_zero_roll':str(zero['roll']),
                'level_zero_pitch':str(zero['pitch']),
            })
            return jsonify(ok=True,mode='operator_zero',**zero)

        # Legacy pre-calibration behaviour is retained until a physical
        # calibration exists, so current cameras do not change unexpectedly.
        cp='/home/pi/gyrologd/level_cal.json'
        cal={'roll':0.0,'pitch':0.0,'shake':0.0}
        try:
            cal.update(_json.load(open(cp)))
        except Exception:
            pass
        cal={
            'roll':round(cal['roll']+g('imu_roll'),2),
            'pitch':round(cal['pitch']+g('imu_pitch'),2),
            'shake':round(cal['shake']+g('imu_shake'),2),
        }
        with open(cp,'w') as f:
            f.write(_json.dumps(cal))
        _subprocess.run(['sudo','systemctl','restart','gyrologd'])
        return jsonify(ok=True,mode='legacy_level_offset',**cal)
    except Exception as e:
        return jsonify(ok=False,error=str(e)),500
