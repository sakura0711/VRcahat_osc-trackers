"""Validate an opt-in Android image/landmark ZIP and build a local overlay viewer.

No network or OSC output. Images are already rotated/mirrored model inputs;
the viewer never mirrors or crops them again.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import struct
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_BYTES = 80 * 1024 * 1024
MAX_PIXELS = 4_194_304
ROLES = {"左髖": 23, "右髖": 24, "左膝": 25, "右膝": 26,
         "左踝": 27, "右踝": 28, "左腳跟": 29, "右腳跟": 30, "左腳尖": 31, "右腳尖": 32}


def png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) > MAX_IMAGE_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid or oversized PNG")
    offset, dimensions, saw_data = 8, None, False
    while offset + 12 <= len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + size
        if end > len(data):
            raise ValueError("truncated PNG")
        kind = data[offset + 4:offset + 8]
        chunk = data[offset + 8:offset + 8 + size]
        crc = struct.unpack_from(">I", data, offset + 8 + size)[0]
        if zlib.crc32(kind + chunk) & 0xFFFFFFFF != crc:
            raise ValueError("PNG checksum mismatch")
        if dimensions is None:
            if kind != b"IHDR" or size != 13:
                raise ValueError("missing PNG dimensions")
            dimensions = struct.unpack_from(">II", chunk)
            w, h = dimensions
            if not w or not h or w * h > MAX_PIXELS:
                raise ValueError("PNG dimensions exceed capture limits")
        if kind == b"IDAT":
            saw_data = True
        if kind == b"IEND":
            if size or end != len(data) or not saw_data:
                raise ValueError("invalid PNG ending")
            return dimensions
        offset = end
    raise ValueError("incomplete PNG")


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name and ":" not in name


def _integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _point_arrays(packet: dict[str, Any]) -> None:
    if type(packet.get("personDetected")) is not bool:
        raise ValueError("invalid personDetected")
    count = 33 if packet["personDetected"] else 0
    for key in ("landmarks", "worldLandmarks"):
        points = packet.get(key)
        if not isinstance(points, list) or len(points) != count:
            raise ValueError("invalid landmark count")
        for point in points:
            if not isinstance(point, dict):
                raise ValueError("invalid landmark")
            for axis in ("x", "y", "z"):
                value = point.get(axis)
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError("nonfinite landmark")
            for key in ("visibility", "presence"):
                value = point.get(key)
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1):
                    raise ValueError("invalid confidence")


def validate_pair(meta: dict[str, Any], image: bytes, session: str) -> None:
    if (not isinstance(meta, dict) or meta.get("format") != "vrchat-track-image-pair" or
            type(meta.get("version")) is not int or meta["version"] != 1 or meta.get("captureSession") != session):
        raise ValueError("unsupported image pair or session mismatch")
    descriptor = meta.get("image", {})
    if not isinstance(descriptor, dict) or descriptor.get("file") != "input.png" or descriptor.get("sha256") != hashlib.sha256(image).hexdigest():
        raise ValueError("image identity/hash mismatch")
    packet = meta.get("packet", {})
    if not isinstance(packet, dict) or type(packet.get("version")) is not int or packet["version"] != 1:
        raise ValueError("unsupported source packet")
    if not _integer(meta.get("frameId")) or not _integer(packet.get("resultTimestampMs")) or packet["resultTimestampMs"] != meta["frameId"]:
        raise ValueError("frame identity mismatch")
    if not _integer(packet.get("captureMonotonicNs")) or not _integer(packet.get("analysisStartMonotonicNs"), 1):
        raise ValueError("missing source frame timestamps")
    if (type(packet.get("mirroredInput")) is not bool or type(packet.get("inputRotationDegrees")) is not int or
            packet["inputRotationDegrees"] not in (0, 90, 180, 270)):
        raise ValueError("missing input orientation")
    if not isinstance(packet.get("modelAsset"), str) or not packet["modelAsset"]:
        raise ValueError("missing model identity")
    dimensions = png_dimensions(image)
    if not all(_integer(packet.get(k), 1) for k in ("imageWidth", "imageHeight")) or dimensions != (packet["imageWidth"], packet["imageHeight"]):
        raise ValueError("image/landmark dimensions mismatch")
    _point_arrays(packet)


def read_pairs(source: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    archive = None
    try:
        if source.is_dir():
            root = source.resolve()
            names = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
            if any(not p.resolve().is_relative_to(root) for p in root.rglob("*")):
                raise ValueError("capture folder contains external links")
            if sum((root / name).stat().st_size for name in names) > MAX_BUNDLE_BYTES:
                raise ValueError("capture exceeds size limit")
            def read(name: str, limit: int) -> bytes:
                with (root / name).open("rb") as stream:
                    value = stream.read(limit + 1)
                if len(value) > limit:
                    raise ValueError("capture file exceeds size limit")
                return value
        else:
            archive = zipfile.ZipFile(source)
            info = [i for i in archive.infolist() if not i.is_dir()]
            names = [i.filename for i in info]
            if len(set(names)) != len(names) or sum(i.file_size for i in info) > MAX_BUNDLE_BYTES:
                raise ValueError("duplicate entries or oversized capture")
            def read(name: str, limit: int) -> bytes:
                with archive.open(name) as stream:
                    value = stream.read(limit + 1)
                if len(value) > limit:
                    raise ValueError("capture file exceeds size limit")
                return value
        if len(names) > 81 or any(not _safe_name(n) for n in names):
            raise ValueError("invalid capture paths or too many entries")
        manifest = json.loads(read("manifest.json", 64 * 1024))
        if not isinstance(manifest, dict) or manifest.get("format") != "vrchat-track-image-pairs" or manifest.get("version") != 1:
            raise ValueError("unsupported image-pair bundle")
        session = manifest.get("captureSession")
        if not isinstance(session, str) or not session:
            raise ValueError("missing capture session")
        metadata = sorted(n for n in names if n.endswith("/landmarks.json"))
        if not 1 <= len(metadata) <= 40:
            raise ValueError("no complete pairs or capture frame limit exceeded")
        frames, seen = [], set()
        for name in metadata:
            parent = PurePosixPath(name).parent
            if len(parent.parts) != 1 or not parent.name.startswith("frame-"):
                raise ValueError("invalid frame directory")
            meta = json.loads(read(name, 256 * 1024))
            image = read(str(parent / "input.png"), MAX_IMAGE_BYTES)
            validate_pair(meta, image, session)
            identity = meta["frameId"]
            if identity in seen:
                raise ValueError("duplicate frame identity")
            seen.add(identity)
            frames.append({"metadata": meta, "png_base64": base64.b64encode(image).decode("ascii")})
        frames.sort(key=lambda f: f["metadata"]["frameId"])
        return manifest, frames
    finally:
        if archive is not None:
            archive.close()


def attach_recording(frames: list[dict[str, Any]], recording: Path) -> None:
    index = {}
    with recording.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("type") != "frame":
                continue
            p = row["packet"]
            key = (p.get("captureMonotonicNs"), p.get("analysisStartMonotonicNs"))
            if key in index:
                raise ValueError("ambiguous frame identity in tracker recording")
            index[key] = row
    for frame in frames:
        packet = frame["metadata"]["packet"]
        key = (packet["captureMonotonicNs"], packet["analysisStartMonotonicNs"])
        row = index.get(key)
        if row is None:
            frame["tracker_record"] = None
            continue
        other = row["packet"]
        if (packet["landmarks"] != other["landmarks"] or packet["worldLandmarks"] != other["worldLandmarks"] or
                any(packet[k] != other[k] for k in ("resultTimestampMs", "imageWidth", "imageHeight", "inputRotationDegrees", "mirroredInput", "modelAsset") if k in other)):
            raise ValueError("same-frame source landmarks do not match tracker recording")
        frame["tracker_record"] = {k: row.get(k) for k in ("at_ns", "diagnostic", "transforms", "height_diagnostics")}
    if not any(frame.get("tracker_record") is not None for frame in frames):
        raise ValueError("no same-frame matches in the supplied tracker recording")


HTML = r'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>同一影格影像與姿勢點</title><style>
body{font:16px system-ui,sans-serif;margin:24px;background:#111827;color:#f1f5f9}h1{font-size:24px}button,input{font:inherit}button{padding:8px 16px;margin:4px}input[type=range]{width:min(60vw,600px)}
.grid{display:grid;grid-template-columns:minmax(280px,1fr) minmax(300px,1fr);gap:24px}canvas{max-width:100%;height:auto;max-height:78vh;object-fit:contain;background:#000}table{border-collapse:collapse;width:100%}td,th{padding:7px;text-align:left;border-bottom:1px solid #374151;font-size:13px}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#cbd5e1}.controls{margin:16px 0}label{margin-right:16px}@media(max-width:850px){.grid{grid-template-columns:1fr}body{margin:12px}}
</style><h1>同一影格影像與姿勢點</h1>
<p>已驗證影像雜湊、尺寸與影格識別。影像是旋轉／鏡像後的模型輸入，完整顯示；不再次鏡像或裁切。此頁離線運作，不送 OSC。</p>
<div class="controls"><button id="previous">上一張</button><input id="frame" aria-label="影格" type="range" min="0" value="0"><button id="next">下一張</button>
<label><input id="overlay" type="checkbox" checked>顯示姿勢點</label><label><input id="indices" type="checkbox">顯示點編號</label></div>
<p id="identity"></p><div class="grid"><div><canvas id="image" aria-label="完整分析影像與關鍵點"></canvas></div><div><p id="details"></p>
<small>左右名稱依此檢視頁指定的角色對調設定；3D 數值是模型估計，不能當外部真值。信心低於 0.5 的點以淡色顯示。</small>
<table><thead><tr><th>角色／索引</th><th>影像 x,y</th><th>3D x,y,z（m）</th><th>信心</th></tr></thead><tbody id="points"></tbody></table><h2>同影格 tracker 診斷</h2><pre id="tracker"></pre></div></div>
<script id="payload" type="application/json">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('payload').textContent), frames=data.frames, roles=data.roles;
const canvas=document.getElementById('image'),ctx=canvas.getContext('2d'),slider=document.getElementById('frame');slider.max=frames.length-1;
const edges=[[11,12],[11,23],[12,24],[23,24],[11,13],[13,15],[12,14],[14,16],[23,25],[25,27],[27,29],[29,31],[27,31],[24,26],[26,28],[28,30],[30,32],[28,32]];
let epoch=0;
function pointPixel(point,width,height){return [point.x*width,point.y*height];}
function confidence(p){let v=[p.visibility,p.presence].filter(x=>x!==null&&x!==undefined);return v.length?Math.min(...v):null;}
function render(){const token=++epoch,f=frames[Number(slider.value)],meta=f.metadata,p=meta.packet;ctx.clearRect(0,0,canvas.width,canvas.height);document.getElementById('points').replaceChildren();document.getElementById('identity').textContent='載入影格…';document.getElementById('details').textContent='';document.getElementById('tracker').textContent='';
 const image=new Image();image.onload=()=>{if(token!==epoch)return;canvas.width=p.imageWidth;canvas.height=p.imageHeight;ctx.drawImage(image,0,0);
 const lm=p.landmarks;if(document.getElementById('overlay').checked){ctx.lineWidth=Math.max(1,p.imageWidth/350);ctx.strokeStyle='#38bdf8';for(const [a,b] of edges){if(!lm[a]||!lm[b])continue;ctx.beginPath();ctx.moveTo(...pointPixel(lm[a],canvas.width,canvas.height));ctx.lineTo(...pointPixel(lm[b],canvas.width,canvas.height));ctx.stroke();}
 lm.forEach((q,i)=>{const [x,y]=pointPixel(q,canvas.width,canvas.height),c=confidence(q);ctx.globalAlpha=c!==null&&c<.5?.3:1;ctx.fillStyle=i>=23?'#fbbf24':'#34d399';ctx.beginPath();ctx.arc(x,y,Math.max(2,p.imageWidth/160),0,2*Math.PI);ctx.fill();if(document.getElementById('indices').checked){ctx.font=Math.max(11,p.imageWidth/35)+'px sans-serif';ctx.fillText(String(i),x+4,y-4);}});ctx.globalAlpha=1;}
 document.getElementById('identity').textContent=`${Number(slider.value)+1} / ${frames.length}｜影格 ${meta.frameId}｜擷取批次 ${meta.captureSession}`;
 document.getElementById('details').textContent=`${p.imageWidth} × ${p.imageHeight}｜輸入鏡像：${p.mirroredInput?'是':'否'}｜已套用相機旋轉：${p.inputRotationDegrees}°｜${p.modelAsset}｜左右角色對調：${data.swap_left_right?'是':'否'}`;
 for(const [name,index] of Object.entries(roles)){const row=document.createElement('tr'),a=lm[index],w=p.worldLandmarks[index];for(const text of [name+' / '+index,a?`${a.x.toFixed(4)}, ${a.y.toFixed(4)}`:'無人體',w?`${w.x.toFixed(4)}, ${w.y.toFixed(4)}, ${w.z.toFixed(4)}`:'—',a?(confidence(a)??'未提供'):'—']){const cell=document.createElement('td');cell.textContent=String(text);row.append(cell);}document.getElementById('points').append(row);}
 document.getElementById('tracker').textContent=f.tracker_record?JSON.stringify(f.tracker_record,null,2):'未連結 tracker 紀錄；影像與來源 landmarks 的配對已通過驗證。';};
 image.src='data:image/png;base64,'+f.png_base64;}
document.getElementById('previous').onclick=()=>{slider.value=Math.max(0,Number(slider.value)-1);render();};document.getElementById('next').onclick=()=>{slider.value=Math.min(frames.length-1,Number(slider.value)+1);render();};slider.oninput=render;document.getElementById('overlay').onchange=render;document.getElementById('indices').onchange=render;render();
</script></html>'''


def render_viewer(frames: list[dict[str, Any]], swap_left_right: bool = False) -> str:
    roles = {name: index + (1 if index % 2 else -1) if swap_left_right else index for name, index in ROLES.items()}
    payload = json.dumps({"frames": frames, "roles": roles, "swap_left_right": swap_left_right}, ensure_ascii=True, allow_nan=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return HTML.replace("__PAYLOAD__", payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="exported ZIP or session directory")
    parser.add_argument("--output", type=Path, required=True, help="new standalone HTML file; never overwrites")
    parser.add_argument("--recording", type=Path, help="optional same-run tracker JSONL for exact timestamp/source matching")
    parser.add_argument("--swap-left-right", action="store_true", help="apply explicitly verified physical-side mapping to labels")
    args = parser.parse_args(argv)
    try:
        _, frames = read_pairs(args.source)
        if args.recording:
            attach_recording(frames, args.recording)
        html = render_viewer(frames, args.swap_left_right)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(html)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        print(f"image-pair error: {error}")
        return 1
    matches = sum(f.get("tracker_record") is not None for f in frames)
    print(f"IMAGE_PAIRS_VERIFIED frames={len(frames)}; tracker_matches={matches}; output={args.output}; no sockets or OSC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
