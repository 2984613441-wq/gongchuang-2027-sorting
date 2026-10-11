import os, re, zipfile
src = r"C:\Users\29845\Desktop\审核v4.0.docx"
out = r"C:\Users\29845\Desktop\工创赛\工具\_review_v4.txt"
print("exists:", os.path.exists(src), "size:", os.path.getsize(src) if os.path.exists(src) else "-")
z = zipfile.ZipFile(src)
doc = z.read("word/document.xml").decode("utf-8", "replace")
# 段落切分，保留结构
paras = re.split(r"</w:p>", doc)
lines = []
for p in paras:
    texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)
    s = "".join(texts).strip()
    if s:
        lines.append(s)
txt = "\n".join(lines)
with open(out, "w", encoding="utf-8") as f:
    f.write(txt)
print("chars:", len(txt), "lines:", len(lines))
print("saved:", out)