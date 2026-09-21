#!/usr/bin/env python3
"""Full-screen HDMI UI for the guided IMU calibration wizard."""
import json
import math
import os
import time

from PIL import Image, ImageDraw, ImageFont


def _rget(gui, key, default=''):
    try:
        raw = gui.redis_controller.r.get(key)
        if raw is None:
            return default
        return raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
    except Exception:
        return default


def is_active(gui):
    return str(_rget(gui, 'imu_cal_active', '0')).strip().lower() in ('1', 'true', 'yes', 'on')


def _status(gui):
    try:
        raw = _rget(gui, 'imu_cal_status', '')
        value = json.loads(raw) if raw else {}
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _font(gui, size, bold=False):
    key = ('imu-cal-ui', int(size), bool(bold))
    cached = gui._font_cache.get(key)
    if cached is not None:
        return cached
    candidates = []
    if bold:
        candidates.extend([
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf',
        ])
    candidates.extend([
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        os.path.realpath(gui.font_path),
    ])
    for path in candidates:
        try:
            f = ImageFont.truetype(path, int(size))
            gui._font_cache[key] = f
            return f
        except Exception:
            pass
    f = ImageFont.load_default()
    gui._font_cache[key] = f
    return f


def _progress(draw, box, value, color=(55, 224, 173, 255)):
    x0, y0, x1, y1 = box
    value = max(0.0, min(1.0, float(value or 0.0)))
    r = max(3, (y1-y0)//2)
    draw.rounded_rectangle(box, radius=r, fill=(27, 42, 52, 255),
                           outline=(59, 83, 95, 255), width=2)
    if value > 0:
        fw = max(y1-y0, int((x1-x0)*value))
        draw.rounded_rectangle((x0, y0, x0+fw, y1), radius=r, fill=color)


def _sphere_points(count):
    golden = math.pi * (3.0 - math.sqrt(5.0))
    out = []
    for i in range(count):
        y = 1.0 - (2.0*i)/max(1, count-1)
        rr = math.sqrt(max(0.0, 1.0-y*y))
        t = golden*i
        out.append((math.cos(t)*rr, y, math.sin(t)*rr))
    return out


def _rotate3(v, yaw, pitch):
    """Rotate world vector into view space."""
    x, y, z = v
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)

    # yaw around world Y
    x1 = cy*x + sy*z
    z1 = -sy*x + cy*z

    # pitch around view X
    y2 = cp*y - sp*z1
    z2 = sp*y + cp*z1
    return x1, y2, z2


def _project3(v, yaw, pitch, radius, perspective=0.22):
    """Perspective-project a unit-sphere point.

    Returns screen-space x/y in sphere-radius units, view-space depth,
    and a perspective scale factor. Positive z faces the viewer.
    """
    x, y, z = _rotate3(v, yaw, pitch)
    # Keep perspective subtle enough to retain globe proportions.
    denom = max(0.60, 1.0 - perspective*z)
    scale = 1.0 / denom
    return x*radius*scale, -y*radius*scale, z, scale


def _sphere_line(draw, points, cx, cy, yaw, pitch, radius, color_front, color_back,
                 width=2, perspective=0.22):
    """Draw a 3D curve with hemisphere-aware visibility.

    Back-facing curve segments are deliberately dimmer and thinner; front
    segments are brighter. This gives the globe an actual 3D topology instead
    of a flat ellipse.
    """
    prev = None
    for v in points:
        px, py, z, _ = _project3(v, yaw, pitch, radius, perspective)
        cur = (cx+px, cy+py, z)
        if prev is not None:
            x0, y0, z0 = prev
            x1, y1, z1 = cur
            zmid = 0.5*(z0+z1)
            if zmid >= 0:
                draw.line((x0,y0,x1,y1), fill=color_front, width=width)
            else:
                draw.line((x0,y0,x1,y1), fill=color_back, width=max(1,width-1))
        prev = cur


def _great_circle(axis, angle, samples=96):
    """Generate a great/small circle family in world space."""
    out=[]
    ca, sa = math.cos(angle), math.sin(angle)

    for i in range(samples+1):
        t = 2.0*math.pi*i/samples
        ct, st = math.cos(t), math.sin(t)

        if axis == 'lat':
            # angle is latitude
            y = sa
            r = ca
            out.append((r*ct, y, r*st))
        else:
            # angle is longitude
            x = math.sin(angle)*ct
            z = math.cos(angle)*ct
            y = st
            out.append((x,y,z))
    return out


def _mesh_cache(gui, count, step_deg=12):
    """Build a real triangulated unit-sphere mesh once per coverage resolution."""
    key=(int(count),int(step_deg))
    cache=getattr(gui,'_imu_mesh_cache',None)
    if cache is None:
        cache={}
        gui._imu_mesh_cache=cache
    if key in cache:
        return cache[key]

    dirs=_sphere_points(count)
    tris=[]
    lat_vals=list(range(-84,85,step_deg))
    lon_vals=list(range(0,360,step_deg))

    def pnt(lat_deg,lon_deg):
        lat=math.radians(lat_deg)
        lon=math.radians(lon_deg)
        c=math.cos(lat)
        return (c*math.cos(lon), math.sin(lat), c*math.sin(lon))

    def nearest_bin(c):
        best_i=0
        best=-2.0
        for i,d in enumerate(dirs):
            q=c[0]*d[0]+c[1]*d[1]+c[2]*d[2]
            if q>best:
                best=q;best_i=i
        return best_i

    for lat0 in lat_vals:
        lat1=min(90,lat0+step_deg)
        for lon0 in lon_vals:
            lon1=(lon0+step_deg)%360
            a=pnt(lat0,lon0); b=pnt(lat1,lon0)
            c=pnt(lat1,lon1); d=pnt(lat0,lon1)
            for tri in ((a,b,c),(a,c,d)):
                center=(
                    sum(v[0] for v in tri)/3.0,
                    sum(v[1] for v in tri)/3.0,
                    sum(v[2] for v in tri)/3.0,
                )
                n=math.sqrt(sum(q*q for q in center)) or 1.0
                center=tuple(q/n for q in center)
                tris.append((tri,center,nearest_bin(center)))

    cache[key]=tris
    return tris


def _sphere(gui, draw, cx, cy, radius, status, compact=False):
    """Software-rendered 3D coverage globe.

    This is a real triangulated sphere in 3D: triangles are rotated, lit,
    projected and back-face culled every frame. Rear geometry is occluded.
    """
    count=max(24,min(256,int(status.get('coverage_count') or 96)))
    covered=set(int(x) for x in (status.get('covered') or []))

    # Slow automatic orbit makes the 3D form and rear-side coverage obvious.
    manual=0.0
    try:
        manual=math.radians(float(_rget(gui,'imu_cal_view_yaw',0) or 0))
    except Exception:
        pass
    yaw=manual + time.monotonic()*0.22
    pitch=math.radians(-14.0)

    tris=_mesh_cache(gui,count,15 if compact else 12)
    light=(-0.45,-0.55,0.78)
    ln=math.sqrt(sum(q*q for q in light))
    light=tuple(q/ln for q in light)

    rendered=[]
    for tri,center,bin_idx in tris:
        rv=[_rotate3(v,yaw,pitch) for v in tri]
        rc=_rotate3(center,yaw,pitch)

        # Sphere normal points outward; positive view-space Z faces viewer.
        if rc[2] <= 0.015:
            continue

        pts=[]
        for x,y,z in rv:
            # Mild perspective, but preserve a physically spherical silhouette.
            sc=1.0/(1.0-0.10*z)
            pts.append((cx+x*radius*sc,cy-y*radius*sc))

        ndotl=max(0.0,rc[0]*light[0]+rc[1]*light[1]+rc[2]*light[2])
        edge=max(0.0,min(1.0,rc[2]))
        illum=0.18+0.58*ndotl+0.24*edge

        if bin_idx in covered:
            base=(46,190,132)
        else:
            base=(42,48,52)

        fill=tuple(max(0,min(255,int(v*illum))) for v in base)+(255,)
        rendered.append((rc[2],pts,fill))

    # Painter order: horizon first, front-most facets last.
    rendered.sort(key=lambda x:x[0])
    for depth,pts,fill in rendered:
        draw.polygon(pts,fill=fill)
        if not compact:
            draw.line(pts+[pts[0]],fill=(28,34,37,255),width=1)

    # Clean silhouette.
    draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),
                 outline=(112,122,127,255),width=2)

    # Current gravity vector.
    v=status.get('current_vector') or [0.0,0.0,1.0]
    try:
        x,y,z=[float(q) for q in v[:3]]
        n=math.sqrt(x*x+y*y+z*z) or 1.0
        rv=_rotate3((x/n,y/n,z/n),yaw,pitch)
        if rv[2] > 0:
            px=cx+rv[0]*radius*0.92
            py=cy-rv[1]*radius*0.92
            draw.line((cx,cy,px,py),fill=(235,235,235,255),width=3 if compact else 5)
            rr=5 if compact else 8
            draw.ellipse((px-rr,py-rr,px+rr,py+rr),fill=(255,255,255,255))
    except Exception:
        pass

    # Nearest still-uncovered target, if currently on visible hemisphere.
    tv=status.get('coverage_target_vector')
    if tv:
        try:
            rv=_rotate3(tuple(float(q) for q in tv[:3]),yaw,pitch)
            if rv[2]>0:
                px=cx+rv[0]*radius*0.96
                py=cy-rv[1]*radius*0.96
                rr=10 if compact else 15
                draw.ellipse((px-rr,py-rr,px+rr,py+rr),
                             outline=(235,174,63,255),width=3)
        except Exception:
            pass

def _gauge(gui, draw, box, title, value, vmax, unit, good, warn):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=18, fill=(16, 27, 36, 255),
                           outline=(52, 75, 88, 255), width=2)
    draw.text((x0+24, y0+18), title, fill=(185, 204, 213, 255), font=_font(gui, 22, True))
    try:
        v = float(value)
    except Exception:
        v = 0.0
    color = (55, 224, 173, 255) if v <= good else ((255, 193, 72, 255) if v <= warn else (255, 91, 94, 255))
    draw.text((x0+24, y0+58), f'{v:.3f}', fill=color, font=_font(gui, 42, True))
    draw.text((x0+165, y0+80), unit, fill=(123, 150, 161, 255), font=_font(gui, 18))
    _progress(draw, (x0+24, y1-42, x1-24, y1-27), min(1.0, v/max(vmax, 1e-9)), color)


def _camera_pose(gui, image, draw, cx, cy, face):
    name = str((face or {}).get('name') or '')
    title = str((face or {}).get('title') or 'POSE')
    cam = Image.new('RGBA', (460, 300), (0,0,0,0))
    d = ImageDraw.Draw(cam)
    d.rounded_rectangle((80, 75, 325, 235), radius=24, fill=(42,55,67,255),
                        outline=(124,164,184,255), width=4)
    d.rounded_rectangle((40, 105, 110, 205), radius=16, fill=(29,39,49,255))
    d.rectangle((325, 115, 405, 195), fill=(55,71,82,255))
    d.ellipse((370, 118, 448, 192), fill=(12,25,34,255),
              outline=(78,202,231,255), width=5)
    d.ellipse((386, 133, 432, 177), fill=(8,14,22,255),
              outline=(43,103,126,255), width=3)
    d.rounded_rectangle((125, 43, 225, 86), radius=10, fill=(54,70,81,255))

    angle = {
        'normal': 0,
        'upside_down': 180,
        'right_down': -90,
        'left_down': 90,
        'lens_down': -90,
        'lens_up': 90,
    }.get(name, 0)
    if angle:
        cam = cam.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
    image.alpha_composite(cam, (int(cx-230), int(cy-150)))

    draw.line((cx+265, cy-100, cx+265, cy+105), fill=(255,196,72,255), width=8)
    draw.polygon([(cx+245,cy+80),(cx+285,cy+80),(cx+265,cy+120)], fill=(255,196,72,255))
    draw.text((cx+215,cy+130), 'GRAVITY', fill=(255,205,95,255), font=_font(gui,18,True))
    tb = draw.textbbox((0,0), title, font=_font(gui,34,True))
    draw.text((cx-(tb[2]-tb[0])//2, cy+185), title, fill=(235,244,248,255), font=_font(gui,34,True))


def _txt(draw,xy,text,font,fill=(225,225,225,255)):
    draw.text(xy,str(text),font=font,fill=fill)


def _bar(draw,box,value,accent=(55,210,145,255)):
    x0,y0,x1,y1=box
    v=max(0.0,min(1.0,float(value or 0.0)))
    draw.rectangle(box,fill=(31,31,31,255))
    if v>0:
        draw.rectangle((x0,y0,x0+(x1-x0)*v,y1),fill=accent)


def draw(gui):
    fb=gui.fb
    if not fb:
        return

    status=_status(gui)
    phase=str(status.get('phase') or 'waiting')
    w,h=fb.size
    sx,sy=w/1920.0,h/1080.0
    X=lambda v:int(v*sx)
    Y=lambda v:int(v*sy)

    BG=(8,8,8,255)
    FG=(230,230,230,255)
    MID=(145,145,145,255)
    DIM=(82,82,82,255)
    LINE=(48,48,48,255)
    GREEN=(55,210,145,255)
    AMBER=(235,174,63,255)
    RED=(220,72,72,255)

    image=Image.new('RGBA',fb.size,BG)
    d=ImageDraw.Draw(image)

    # Header: information only, no decorative chrome.
    _txt(d,(X(54),Y(34)),'IMU CALIBRATION',_font(gui,Y(30),True),FG)
    phase_map={
        'intro':'PREP','gyro':'GYRO ZERO','gyro_done':'GYRO ZERO',
        'tumble':'ACCEL COVERAGE','accel_done':'ACCEL COVERAGE',
        'faces':'CAMERA ALIGNMENT','results':'RESULTS',
        'saved':'SAVED','cancelled':'CANCELLED'
    }
    _txt(d,(X(54),Y(78)),phase_map.get(phase,phase.upper()),_font(gui,Y(17),True),MID)
    temp=status.get('temperature_c')
    if temp is not None:
        t=f'{float(temp):.1f} °C'
        tb=d.textbbox((0,0),t,font=_font(gui,Y(18),False))
        _txt(d,(w-X(54)-(tb[2]-tb[0]),Y(48)),t,_font(gui,Y(18)),MID)
    d.line((X(54),Y(112),w-X(54),Y(112)),fill=LINE,width=1)

    message=str(status.get('message') or '')
    progress=float(status.get('progress') or 0.0)

    if phase=='intro':
        _sphere(gui,d,X(550),Y(565),Y(300),status)
        _txt(d,(X(1010),Y(280)),'Four measurements.',_font(gui,Y(38),True),FG)
        rows=[
            ('01','Gyro bias','8 s completely still'),
            ('02','Accelerometer','tumble through gravity directions'),
            ('03','Camera frame','six stable physical poses'),
            ('04','Validation','review errors before saving'),
        ]
        for i,(n,a,b) in enumerate(rows):
            yy=Y(390+i*105)
            _txt(d,(X(1010),yy),n,_font(gui,Y(19),True),DIM)
            _txt(d,(X(1080),yy-Y(4)),a,_font(gui,Y(25),True),FG)
            _txt(d,(X(1080),yy+Y(34)),b,_font(gui,Y(18)),MID)
        _txt(d,(X(1010),Y(850)),'Start from the web control.',_font(gui,Y(21),True),GREEN)

    elif phase in ('gyro','gyro_done'):
        pct=int(progress*100)
        _txt(d,(X(160),Y(330)),f'{pct:02d}%',_font(gui,Y(112),True),FG)
        _bar(d,(X(165),Y(485),X(850),Y(505)),progress,GREEN)
        _txt(d,(X(165),Y(540)),message,_font(gui,Y(24)),MID)
        _txt(d,(X(1080),Y(330)),'KEEP CAMERA STILL',_font(gui,Y(34),True),FG)
        resets=int(status.get('gyro_motion_resets') or 0)
        _txt(d,(X(1080),Y(410)),f'movement resets  {resets}',_font(gui,Y(21)),AMBER if resets else MID)
        if phase=='gyro_done':
            bias=status.get('gyro_bias_dps') or [0,0,0]
            noise=float(status.get('gyro_noise_rms_dps') or 0.0)
            yy=Y(545)
            _txt(d,(X(1080),yy),'bias °/s',_font(gui,Y(18),True),MID)
            for i,ax in enumerate('XYZ'):
                _txt(d,(X(1080),yy+Y(50+i*44)),f'{ax}  {float(bias[i]):+.4f}',_font(gui,Y(25),True),FG)
            _txt(d,(X(1450),yy),'noise RMS',_font(gui,Y(18),True),MID)
            _txt(d,(X(1450),yy+Y(50)),f'{noise:.4f} °/s',_font(gui,Y(28),True),GREEN)

    elif phase in ('tumble','accel_done'):
        _sphere(gui,d,X(560),Y(565),Y(345),status)
        cov=float(status.get('coverage') or 0.0)
        fitn=int(status.get('fit_samples') or 0)
        obs=int(status.get('coverage_observations') or 0)

        _txt(d,(X(1040),Y(280)),f'{cov*100:.0f}%',_font(gui,Y(94),True),GREEN if cov>=.70 else FG)
        _txt(d,(X(1045),Y(385)),'gravity-direction coverage',_font(gui,Y(20),True),MID)
        _bar(d,(X(1045),Y(430),X(1770),Y(450)),cov,GREEN)

        _txt(d,(X(1045),Y(515)),message,_font(gui,Y(23)),FG)
        _txt(d,(X(1045),Y(600)),'Do:',_font(gui,Y(18),True),MID)
        _txt(d,(X(1110),Y(600)),'slow roll + pitch + tumble',_font(gui,Y(20)),FG)
        _txt(d,(X(1045),Y(645)),'Not useful:',_font(gui,Y(18),True),MID)
        _txt(d,(X(1175),Y(645)),'spinning around vertical',_font(gui,Y(20)),FG)

        _txt(d,(X(1045),Y(735)),f'accepted directions  {obs}',_font(gui,Y(18)),MID)
        _txt(d,(X(1045),Y(775)),f'clean fit samples     {fitn}',_font(gui,Y(18)),MID)

        if phase=='accel_done':
            m=status.get('accel_metrics') or {}
            before=float(m.get('before_norm_rms_g') or 0)
            after=float(m.get('after_norm_rms_g') or 0)
            _txt(d,(X(1045),Y(845)),f'gravity RMS  {before:.4f} g  →  {after:.4f} g',
                 _font(gui,Y(22),True),GREEN)

    elif phase=='faces':
        face=status.get('face') or {}
        idx=int(face.get('index') or 0)
        count=int(face.get('count') or 6)
        title=str(face.get('title') or 'POSE')
        instr=str(face.get('instruction') or message)

        _txt(d,(X(170),Y(310)),f'{idx+1}/{count}',_font(gui,Y(72),True),DIM)
        _txt(d,(X(420),Y(305)),title,_font(gui,Y(54),True),FG)
        _txt(d,(X(425),Y(390)),instr,_font(gui,Y(25)),MID)

        # Minimal physical orientation cue.
        cx,cy=X(760),Y(665)
        d.rectangle((cx-X(180),cy-Y(95),cx+X(180),cy+Y(95)),outline=FG,width=4)
        d.ellipse((cx+X(145),cy-Y(55),cx+X(255),cy+Y(55)),outline=FG,width=4)
        d.line((cx,cy-Y(150),cx,cy+Y(170)),fill=AMBER,width=5)
        d.polygon([(cx-X(14),cy+Y(145)),(cx+X(14),cy+Y(145)),(cx,cy+Y(180))],fill=AMBER)

        for i in range(count):
            yy=Y(570+i*48)
            mark='●' if i<idx else ('○' if i==idx else '·')
            col=GREEN if i<idx else (FG if i==idx else DIM)
            _txt(d,(X(1260),yy),mark,_font(gui,Y(22),True),col)
            _txt(d,(X(1310),yy),f'pose {i+1}',_font(gui,Y(20),i==idx),col)

        if face.get('capturing'):
            _txt(d,(X(1260),Y(890)),str(face.get('message') or 'hold still'),_font(gui,Y(24),True),AMBER)

    elif phase=='results':
        res=status.get('results') or {}
        grade=str(res.get('grade') or 'retry').upper()
        col=GREEN if grade=='GOOD' else (AMBER if grade=='MARGINAL' else RED)
        _txt(d,(X(150),Y(240)),grade,_font(gui,Y(76),True),col)

        metrics=[
            ('gyro noise',float(res.get('gyro_noise_rms_dps') or 0),'°/s',.20,.50),
            ('accel RMS',float(res.get('accel_after_norm_rms_g') or 0),'g',.035,.070),
            ('alignment max',float(res.get('face_max_error_deg') or 0),'°',6.0,12.0),
            ('coverage',100*float(res.get('coverage') or status.get('coverage') or 0),'%',82.0,70.0),
        ]
        y=Y(390)
        for name,val,unit,good,warn in metrics:
            _txt(d,(X(160),y),name,_font(gui,Y(21),True),MID)
            _txt(d,(X(520),y-Y(5)),f'{val:.3f} {unit}',_font(gui,Y(30),True),FG)
            d.line((X(160),y+Y(45),X(1760),y+Y(45)),fill=LINE,width=1)
            y+=Y(105)

        _sphere(gui,d,X(1530),Y(325),Y(150),status,compact=True)
        _txt(d,(X(160),Y(865)),'Choose RETRY / SAVE / CANCEL from the web UI.',_font(gui,Y(22),True),FG)

    else:
        txt='Calibration saved.' if phase=='saved' else (
            'Calibration cancelled. Previous calibration retained.' if phase=='cancelled'
            else 'Waiting for calibration service.'
        )
        _txt(d,(X(160),Y(470)),txt,_font(gui,Y(42),True),FG)

    # Bottom status strip.
    d.line((X(54),Y(982),w-X(54),Y(982)),fill=LINE,width=1)
    footer='CONTROL FROM WEB UI   •   http://cinepi:5000'
    _txt(d,(X(54),Y(1005)),footer,_font(gui,Y(17),True),MID)

    notice=str(_rget(gui,'imu_cal_notice','') or '')
    if notice:
        tb=d.textbbox((0,0),notice,font=_font(gui,Y(17),True))
        _txt(d,(w-X(54)-(tb[2]-tb[0]),Y(1005)),notice,_font(gui,Y(17),True),AMBER)

    try:
        fb.show(image)
    except (OSError,RuntimeError,ValueError) as exc:
        if hasattr(gui,'logger'):
            gui.logger.warning('Calibration framebuffer write failed: %s',exc)
        if gui.fb is fb:
            gui.fb=None
            gui.disp_width=0
            gui.disp_height=0

