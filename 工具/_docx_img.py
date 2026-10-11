import os, re, zipfile
src = r"C:\Users\29845\Desktop\屏幕照片.docx"
out = r"C:\Users\29845\Desktop\工创赛\工具\object_images"
os.makedirs(out, exist_ok=True)
z = zipfile.ZipFile(src)
media = [n for n in z.namelist() if n.startswith("word/media/") and not n.endswith("/")]
print("media count:", len(media))
for n in sorted(media):
    name = os.path.basename(n)
    if not name:
        continue
    data = z.read(n)
    with open(os.path.join(out, name), "wb") as f:
        f.write(data)
    print("  %-30s %8d bytes" % (name, len(data)))
doc = z.read("word/document.xml").decode("utf-8", "replace")
texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", doc)
joined = "".join(texts).strip()
print("--- 正文文字 ---")
print(joined[:1000] if joined else "(无文字)")