"""Builds geo/puma_names_2020.json ({"SSPPPPP": "name"}) from the Census Bureau's 2024 TIGER/Line PUMA files.
IPUMS gives PUMA as a bare number; these are the official 2020 PUMA names. Run once; the output is committed.

    python geo/fetch_puma_names.py
"""
import io, json, re, struct, urllib.request, zipfile
from pathlib import Path

BASE = "https://www2.census.gov/geo/tiger/TIGER2024/PUMA20/"
UA = {"User-Agent": "Mozilla/5.0"}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()


def read_dbf(data):
    n, hl, rl = struct.unpack("<IHH", data[4:12])
    fields, off = [], 32
    while data[off] != 0x0D:
        fields.append((data[off:off + 11].split(b"\0")[0].decode(), data[off + 16])); off += 32
    for i in range(n):
        r, pos, rec = data[hl + i * rl + 1: hl + (i + 1) * rl], 0, {}
        for name, ln in fields:
            rec[name] = r[pos:pos + ln].decode("latin1").strip(); pos += ln
        yield rec


names = {}
for f in sorted(set(re.findall(r'href="(tl_2024_\d\d_puma20\.zip)"', get(BASE).decode()))):
    z = zipfile.ZipFile(io.BytesIO(get(BASE + f)))
    dbf = z.read(next(n for n in z.namelist() if n.endswith(".dbf")))
    for rec in read_dbf(dbf):
        names[rec["GEOID20"]] = re.sub(r" PUMA$", "", rec["NAMELSAD20"])
out = Path(__file__).with_name("puma_names_2020.json")
out.write_text(json.dumps(dict(sorted(names.items())), indent=0, ensure_ascii=False))
print(len(names), "PUMAs ->", out)
