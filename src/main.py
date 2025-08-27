# -*- coding: utf-8 -*-
from __future__ import annotations

import os, io, math
from typing import List, Optional
from flask import Flask, render_template, request, send_file, jsonify
from pydub import AudioSegment, effects
from pydub.generators import WhiteNoise, Sine

# ===== chemins (…/aqua-confluence-quintuple/src) =====
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))  # …/src
ROOT_DIR      = os.path.dirname(BASE_DIR)                   # …/
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR    = os.path.join(BASE_DIR, "static")
UPLOAD_FOLDER = os.path.join(ROOT_DIR, "uploads")
OUTPUT_FOLDER = os.path.join(ROOT_DIR, "outputs")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.config["_LAST_MIX"] = None
app.config["_LAST_MIX_PATH"] = None

# ===== utils audio =====
def _safe_gain(seg: AudioSegment, db: float) -> AudioSegment:
    try:
        return seg.apply_gain(db)
    except:
        return seg

def _match_rms(ref: AudioSegment, tgt: AudioSegment) -> AudioSegment:
    if tgt.rms == 0 or ref.rms == 0:
        return tgt
    ref_db = 20 * math.log10(ref.rms)
    tgt_db = 20 * math.log10(tgt.rms)
    return _safe_gain(tgt, ref_db - tgt_db)

def _pan(seg: AudioSegment, pan: float) -> AudioSegment:
    try:
        return seg.pan(pan)  # [-1..+1]
    except:
        return seg

def _limiter(seg: AudioSegment, headroom_db: float = 1.0) -> AudioSegment:
    try:
        pk = seg.max_dBFS
        if pk > -headroom_db:
            seg = seg.apply_gain(-headroom_db - pk)
    except:
        pass
    return seg

def _load_one(path: str) -> Optional[AudioSegment]:
    if not path or not os.path.exists(path):
        return None
    try:
        return AudioSegment.from_file(path)
    except:
        return None

def _first_existing(basename: str) -> Optional[AudioSegment]:
    for ext in (".wav", ".mp3", ".flac", ".m4a", ".ogg"):
        seg = _load_one(os.path.join(UPLOAD_FOLDER, f"{basename}{ext}"))
        if seg is not None:
            return seg
    return None

def _build_ambience(kind: str, dur_ms: int, gain_db: float = -24.0) -> Optional[AudioSegment]:
    if not kind or kind == "none":
        return None
    if kind == "water":
        amb = WhiteNoise().to_audio_segment(duration=dur_ms).apply_gain(-12)
        amb = effects.low_pass_filter(amb, 900)
    elif kind == "wind":
        amb = WhiteNoise().to_audio_segment(duration=dur_ms).apply_gain(-14)
        amb = effects.low_pass_filter(amb, 400)
        amb = effects.high_pass_filter(amb, 80)
    elif kind == "pads":
        a = Sine(220).to_audio_segment(duration=dur_ms).apply_gain(-18)
        b = Sine(330).to_audio_segment(duration=dur_ms).apply_gain(-20)
        amb = a.overlay(b)
        amb = effects.low_pass_filter(amb, 1500)
    else:
        return None
    return _safe_gain(amb, gain_db)

# --- helper: purge des anciens fichiers restés dans /uploads ---
def _purge_uploads_except(keep_basenames: set):
    """
    Supprime dans UPLOAD_FOLDER tout ce qui n'est pas listé dans keep_basenames.
    Ex.: keep_basenames = {"M1","M2"} -> on supprime les anciens M3/M4/M5.
    """
    for name in os.listdir(UPLOAD_FOLDER):
        p = os.path.join(UPLOAD_FOLDER, name)
        if not os.path.isfile(p):
            continue
        base = os.path.splitext(name)[0]  # "M1", "M2", ...
        if base not in keep_basenames:
            try:
                os.remove(p)
            except:
                pass

# ===== mix overlay (equal-power) + ambiance =====
def confluence_quintuple(
    tracks: List[Optional[AudioSegment]],
    mode: str = "tao",
    offsets_ms: Optional[List[int]] = None,
    xf_ms: Optional[List[int]] = None,
    gains_db: Optional[List[float]] = None,
    pan_vals: Optional[List[float]] = None,
    ambience: Optional[AudioSegment] = None
) -> Optional[AudioSegment]:
    """
    Mix 1..5 pistes avec crossfades equal-power.
    - TAO : offsets = positions absolues (ms depuis 0)
    - LIAM: offsets = avance (ms) AVANT la fin de la piste précédente
    """
    n = 5
    offsets_ms = (offsets_ms or [0, 14000, 28000, 42000, 56000])[:n]
    xf_ms      = (xf_ms      or [0, 5000, 5000, 5000, 5000])[:n]
    gains_db   = (gains_db   or [0, 0, 0, 0, 0])[:n]
    pan_vals   = (pan_vals   or [0.0, -0.35, 0.35, -0.2, 0.2])[:n]

    if not any(tracks):
        return None

    # référence = 1re piste existante
    ref_idx = next((i for i,t in enumerate(tracks) if t is not None), None)
    if ref_idx is None:
        return None

    base = tracks[ref_idx]
    norm: List[Optional[AudioSegment]] = []
    for i in range(n):
        t = tracks[i]
        if t is None:
            norm.append(None); continue
        # RMS → base
        if t.rms and base.rms:
            ref_db = 20 * math.log10(base.rms)
            t_db   = 20 * math.log10(t.rms)
            t = t.apply_gain(ref_db - t_db)
        # user gain/pan
        if i < len(gains_db): t = t.apply_gain(gains_db[i])
        if i < len(pan_vals):
            try: t = t.pan(pan_vals[i])
            except: pass
        norm.append(t)

    # canevas
    final = norm[ref_idx]
    starts = [0]*n
    starts[ref_idx] = 0

    # place M2..M5
    for i in range(n):
        if i == ref_idx:
            continue
        t = norm[i]
        if t is None:
            continue

        # calcule start
        if mode.lower() == "liam":
            # cherche la précédente
            prev = None
            for j in range(i-1, -1, -1):
                if norm[j] is not None:
                    prev = j; break
            if prev is None:
                start = 0
            else:
                prev_end = starts[prev] + len(norm[prev])
                rel = int(offsets_ms[i]) if i < len(offsets_ms) else 0
                start = max(0, prev_end - rel)
        else:
            start = max(0, int(offsets_ms[i]))

        starts[i] = start
        xf = max(0, int(xf_ms[i] if i < len(xf_ms) else 0))

        need_len = start + len(t)
        if len(final) < need_len:
            final += AudioSegment.silent(duration=need_len - len(final))

        if xf > 0:
            overlap = final[start:start+xf]
            if len(overlap) < xf:
                overlap += AudioSegment.silent(duration=xf - len(overlap))
            fade_in  = t[:xf].fade(from_gain=-60.0, start=0, duration=xf)
            fade_out = overlap.fade(to_gain=-60.0, start=0, duration=xf)
            mixed = fade_out.overlay(fade_in)
            final = final[:start] + mixed + final[start+xf:]
            if len(t) > xf:
                final = final.overlay(t[xf:], position=start+xf)
        else:
            final = final.overlay(t, position=start)

    if ambience:
        if len(ambience) < len(final):
            ambience = ambience + AudioSegment.silent(duration=len(final) - len(ambience))
        final = final.overlay(ambience)

    # limiteur soft
    try:
        pk = final.max_dBFS
        if pk > -1.0:
            final = final.apply_gain(-1.0 - pk)
    except:
        pass

    return final

# ===== concat simple (sans fondu) =====
def concat_tracks(tracks: List[Optional[AudioSegment]]) -> Optional[AudioSegment]:
    segs = [t for t in tracks if t is not None]
    if not segs:
        return None
    out = AudioSegment.silent(duration=0)
    for s in segs:
        out += s
    return _limiter(out, 1.0)

# ===== chargement + offsets relatifs→absolus =====
def _load_M1_M5():
    return [
        _first_existing("M1"),
        _first_existing("M2"),
        _first_existing("M3"),
        _first_existing("M4"),
        _first_existing("M5"),
    ]

def _build_absolute_offsets_from_relative(tracks, rel_ms: List[int]) -> List[int]:
    """
    rel>0 : Mi démarre rel ms AVANT la fin de M(i-1)
    rel=0 : Mi démarre EXACTEMENT à la fin de M(i-1)
    rel<0 : Mi démarre |rel| ms APRÈS la fin de M(i-1)
    """
    offsets = [0,0,0,0,0]
    def prev_existing(i):
        j = i-1
        while j >= 0 and (j >= len(tracks) or tracks[j] is None):
            j -= 1
        return j
    for i in range(1,5):
        if i >= len(tracks) or tracks[i] is None:
            continue
        j = prev_existing(i)
        if j < 0:
            offsets[i] = 0
        else:
            prev_end = offsets[j] + len(tracks[j])
            r = int(rel_ms[i]) if i < len(rel_ms) else 0
            offsets[i] = max(0, prev_end - r)
    return offsets

# ===== parsing commun =====
def _parse_common_json(data):
    mode     = (data.get("mode") or "tao").lower()    # "tao"|"liam"
    engine   = (data.get("engine") or "mix").lower()  # "mix"|"concat"
    amb_name = (data.get("ambience") or "none").lower()
    amb_gain = float(data.get("amb_gain_db") or -24)
    gains    = data.get("gains_db") or [0,0,0,0,0]
    pans     = data.get("pan") or [0.0,-0.35,0.35,-0.2,0.2]
    xfs      = data.get("xf_ms") or [0,5000,5000,5000,5000]

    offset_mode = (data.get("offset_mode") or ("relative_end" if mode=="liam" else "abs")).lower()
    if offset_mode == "relative_end":
        rel = data.get("rel_ms") or [0,0,0,0,0]
        return mode, engine, amb_name, amb_gain, gains, pans, xfs, offset_mode, rel
    else:
        offs = data.get("offsets_ms") or [0,14000,28000,42000,56000]
        return mode, engine, amb_name, amb_gain, gains, pans, xfs, offset_mode, offs

# ===== routes =====
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/health")
def health():
    return {"ok": True, "version": "quintuple-v5"}

@app.route("/upload", methods=["POST"])
def upload():
    sent = set()
    for i in range(1,6):
        f = request.files.get(f"file{i}")
        if f:
            sent.add(f"M{i}")
            name = f"M{i}{os.path.splitext(f.filename)[1].lower() or '.wav'}"
            f.save(os.path.join(UPLOAD_FOLDER, name))
    if sent:
        _purge_uploads_except(sent)
    return jsonify({"success": bool(sent)})

@app.route("/status/durations", methods=["GET"])
def durations():
    tr = _load_M1_M5()
    durs = [(len(t) if t else 0) for t in tr]
    return jsonify({"durations_ms": durs})

@app.route("/preview", methods=["POST"])
def preview():
    data = request.get_json(silent=True) or {}
    tr = _load_M1_M5()
    if not any(tr):
        return jsonify({"success": False, "error": "Aucun affluent (M1..M5)."}), 400

    preview_full = bool(data.get("preview_full", True))  # ← par défaut: mix complet

    mode, engine, amb_name, amb_gain, gains, pans, xfs, offset_mode, offs_or_rel = _parse_common_json(data)
    if engine == "concat":
        mix = concat_tracks(tr)
    else:
        if offset_mode == "relative_end":
            offsets = _build_absolute_offsets_from_relative(tr, offs_or_rel)
            print(f"[LIAM] rel_ms={offs_or_rel} -> offsets_abs={offsets}")
        else:
            offsets = offs_or_rel
            print(f"[TAO] offsets_abs={offsets}")
        amb = _build_ambience(amb_name, max(len(t) for t in tr if t), amb_gain)
        mix = confluence_quintuple(tr, mode, offsets, xfs, gains, pans, amb)

    if mix is None:
        return jsonify({"success": False, "error": "Preview impossible."}), 400

    if preview_full:
        buf = io.BytesIO()
        mix.export(buf, format="wav"); buf.seek(0)
        return send_file(buf, as_attachment=False, download_name="preview.wav", mimetype="audio/wav")
    else:
        # fenêtre ~30s autour de l'entrée de M2
        off2 = 0
        if engine == "mix":
            if offset_mode == "relative_end":
                offsets = _build_absolute_offsets_from_relative(tr, offs_or_rel)
            else:
                offsets = offs_or_rel
            if len(offsets)>1: off2 = int(offsets[1])
        center = max(0, off2 + 2500)
        start  = max(0, center - 15000)
        end    = min(len(mix), start + 30000)
        prev   = mix[start:end]
        buf = io.BytesIO()
        prev.export(buf, format="wav"); buf.seek(0)
        return send_file(buf, as_attachment=False, download_name="preview.wav", mimetype="audio/wav")

@app.route("/render", methods=["POST"])
def render_route():
    data = request.get_json(silent=True) or {}
    tr = _load_M1_M5()
    if not any(tr):
        return jsonify({"success": False, "error": "Aucun affluent (M1..M5)."}), 400

    mode, engine, amb_name, amb_gain, gains, pans, xfs, offset_mode, offs_or_rel = _parse_common_json(data)
    if engine == "concat":
        mix = concat_tracks(tr)
    else:
        if offset_mode == "relative_end":
            offsets = _build_absolute_offsets_from_relative(tr, offs_or_rel)
            print(f"[LIAM] rel_ms={offs_or_rel} -> offsets_abs={offsets}")
        else:
            offsets = offs_or_rel
            print(f"[TAO] offsets_abs={offsets}")
        amb = _build_ambience(amb_name, max(len(t) for t in tr if t), amb_gain)
        mix = confluence_quintuple(tr, mode, offsets, xfs, gains, pans, amb)

    if mix is None:
        return jsonify({"success": False, "error": "Mix impossible."}), 400

    app.config["_LAST_MIX"] = mix
    out_tmp = os.path.join(OUTPUT_FOLDER, "delta_puissant_tmp.wav")
    mix.export(out_tmp, format="wav")
    app.config["_LAST_MIX_PATH"] = out_tmp

    return jsonify({
        "success": True,
        "details": {
            "affluents_count": sum(1 for t in tr if t),
            "total_duration": round(len(mix)/1000.0, 3),
            "format": "wav",
            "file_size": f"{os.path.getsize(out_tmp)//1024} KB"
        },
        "download_url": "/export",
        "output_file": "delta_puissant_tmp.wav"
    })

@app.route("/concat", methods=["POST"])
def concat_route():
    tr = _load_M1_M5()
    if not any(tr):
        return jsonify({"success": False, "error": "Aucun affluent."}), 400
    mix = concat_tracks(tr)
    if mix is None:
        return jsonify({"success": False, "error": "Concat impossible."}), 400
    app.config["_LAST_MIX"] = mix
    out_tmp = os.path.join(OUTPUT_FOLDER, "delta_puissant_tmp.wav")
    mix.export(out_tmp, format="wav")
    app.config["_LAST_MIX_PATH"] = out_tmp
    return jsonify({
        "success": True,
        "details": {
            "affluents_count": sum(1 for t in tr if t),
            "total_duration": round(len(mix)/1000.0, 3),
            "format": "wav",
            "file_size": f"{os.path.getsize(out_tmp)//1024} KB"
        },
        "download_url": "/export",
        "output_file": "delta_puissant_tmp.wav"
    })

@app.route("/export", methods=["POST"])
def export_route():
    data = request.get_json(silent=True) or {}
    fmt = (data.get("format") or "wav").lower()
    br  = data.get("bitrate") or "192k"
    mono = bool(data.get("mono", False))

    mix = app.config.get("_LAST_MIX")
    if mix is None:
        path = app.config.get("_LAST_MIX_PATH")
        if path and os.path.exists(path):
            return send_file(path, as_attachment=True, download_name=os.path.basename(path), mimetype="audio/wav")
        return jsonify({"error": "Pas de mix en mémoire. Cliquez d’abord sur « Créer le delta »."}), 409

    if mono:
        mix = mix.set_channels(1)

    buf = io.BytesIO()
    if fmt == "mp3":
        mix.export(buf, format="mp3", bitrate=br)
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name="delta_puissant.mp3", mimetype="audio/mpeg")
    elif fmt == "flac":
        mix.export(buf, format="flac")
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name="delta_puissant.flac", mimetype="audio/flac")
    else:
        mix.export(buf, format="wav")
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name="delta_puissant.wav", mimetype="audio/wav")

# Local dev only; en prod c'est gunicorn qui lance `app`
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
