#!/usr/bin/env python3
"""Generate the official CinePi Rec.709 display-look LUT pack."""
from pathlib import Path
import hashlib, json

SIZE = 33
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "luts"

def clamp(x):
    return max(0.0, min(1.0, x))

def luma(rgb):
    r,g,b = rgb
    return 0.2126*r + 0.7152*g + 0.0722*b

def contrast(rgb, amount):
    out=[]
    for x in rgb:
        y = x + amount * 4.0 * x * (1.0-x) * (x-0.5)
        out.append(clamp(y))
    return tuple(out)

def saturation(rgb, amount):
    y=luma(rgb)
    return tuple(clamp(y + amount*(c-y)) for c in rgb)

def smoothstep(a,b,x):
    if a==b:
        return 1.0 if x>=b else 0.0
    t=clamp((x-a)/(b-a))
    return t*t*(3-2*t)

def natural(rgb):
    # Still intentionally restrained, but clearly distinguishable from the
    # identity/reference transform on a calibrated Rec.709 display.
    return saturation(contrast(rgb,0.085),1.035)

def filmic_neutral(rgb):
    # More visible filmic separation while remaining a neutral look:
    # firmer midtone contrast, slightly reduced saturation, cool shadows and
    # warm highlights. Endpoints remain well behaved.
    v=saturation(contrast(rgb,0.180),0.925)
    y=luma(v)
    sh=1.0-smoothstep(0.10,0.50,y)
    hi=smoothstep(0.48,0.92,y)
    r,g,b=v
    return (clamp(r - 0.0070*sh + 0.0140*hi),
            clamp(g + 0.0015*sh + 0.0030*hi),
            clamp(b + 0.0130*sh - 0.0110*hi))

def cinema_warm(rgb):
    # Deliberately visible warm cinema look. Warmth is concentrated in
    # midtones/highlights while shadows stay slightly cool, so it remains
    # different from merely changing camera white balance.
    v=saturation(contrast(rgb,0.155),1.010)
    y=luma(v)
    sh=1.0-smoothstep(0.10,0.46,y)
    warm=smoothstep(0.16,0.48,y)*(1.0-0.30*smoothstep(0.82,1.0,y))
    r,g,b=v
    return (clamp(r - 0.0040*sh + 0.0320*warm),
            clamp(g + 0.0015*sh + 0.0090*warm),
            clamp(b + 0.0100*sh - 0.0270*warm))

def soft_portrait(rgb):
    # Softer contrast, reduced saturation and a visible but restrained warm
    # midtone bias. Kept substantially gentler than Cinema Warm.
    v=saturation(contrast(rgb,0.025),0.945)
    y=luma(v)
    mid=smoothstep(0.14,0.44,y)*(1.0-smoothstep(0.62,0.92,y))
    r,g,b=v
    return (clamp(r + 0.0180*mid),
            clamp(g + 0.0060*mid),
            clamp(b - 0.0090*mid))

def identity(rgb):
    return rgb

LOOKS = [
    ("cinepi-rec709-reference.cube", "CinePi Rec.709 Reference", "technical",
     identity, 100,
     "Identity reference LUT for a CinePi Rec.709 display-referred signal."),
    ("cinepi-natural.cube", "CinePi Natural", "natural",
     natural, 100,
     "Subtle neutral monitoring look with gentle contrast and saturation."),
    ("cinepi-filmic-neutral.cube", "CinePi Filmic Neutral", "cinematic",
     filmic_neutral, 100,
     "Restrained filmic contrast with very small split-tone separation."),
    ("cinepi-cinema-warm.cube", "CinePi Cinema Warm", "cinematic",
     cinema_warm, 100,
     "Moderately warm cinematic rendering with controlled cool shadows."),
    ("cinepi-soft-portrait.cube", "CinePi Soft Portrait", "portrait",
     soft_portrait, 100,
     "Gentle portrait rendering with softer contrast and subtly warm mids."),
]

def write_cube(path, title, fn):
    lines=[
        f'TITLE "{title}"',
        f'LUT_3D_SIZE {SIZE}',
        'DOMAIN_MIN 0.0 0.0 0.0',
        'DOMAIN_MAX 1.0 1.0 1.0',
    ]
    den=SIZE-1
    for b in range(SIZE):
        for g in range(SIZE):
            for r in range(SIZE):
                out=fn((r/den,g/den,b/den))
                lines.append(f"{out[0]:.9f} {out[1]:.9f} {out[2]:.9f}")
    path.write_text("\n".join(lines)+"\n")

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for filename,title,category,fn,mix,description in LOOKS:
        cube=OUT/filename
        write_cube(cube,title,fn)
        raw=cube.read_bytes()
        sha=hashlib.sha256(raw).hexdigest()
        meta={
            "display_name":title,
            "source":"CinePi generated",
            "source_url":None,
            "input_space":"CinePi Rec.709 display-referred (BT.709 primaries / BT.709 transfer)",
            "output_space":"CinePi Rec.709 display-referred creative look",
            "interpolation":"tetrahedral",
            "category":category,
            "recommended_mix_percent":mix,
            "official_cinepi":True,
            "redistributable_by_cinepi":True,
            "release_license":"pending-project-license",
            "generator":"tools/generate_cinepi_luts.py",
            "description":description,
            "verified":True,
            "sha256":sha
        }
        cube.with_suffix(".json").write_text(json.dumps(meta,indent=2)+"\n")
        manifest.append({"file":filename,"sha256":sha,"title":title})
        print(title, sha)
    (OUT/"cinepi-official-manifest.json").write_text(
        json.dumps({"format":1,"size":SIZE,"looks":manifest},indent=2)+"\n"
    )

if __name__=="__main__":
    main()
