import os, glob, sys
import fitz
base = r"C:\Users\29845\Desktop\第四期选题咨询会\自适应机械爪"
out  = r"C:\Users\29845\Desktop\工创赛\工具\_z_ref\txt"
os.makedirs(out, exist_ok=True)
targets = []
for pat in ["HX-06L总线串行舵机.pdf","00 产品功能介绍\\产品功能介绍.pdf",
            "04 常见问题解决方法\\自适应机械爪常见问题解决方法.pdf",
            "幻尔科技总线舵机通信协议.pdf","舵机选型手册 .pdf",
            "01 到手检测\\上手测试.pdf","01 到手检测\\总线舵机调试板教程\\舵机调试板使用教程.pdf"]:
    p = os.path.join(base, pat)
    if os.path.exists(p): targets.append(p)
for p in targets:
    try:
        d = fitz.open(p)
        txt = "\n".join(pg.get_text() for pg in d)
        name = os.path.splitext(os.path.basename(p))[0] + ".txt"
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(txt)
        print("OK  %-6d chars  %s" % (len(txt), name))
    except Exception as e:
        print("ERR %s -> %s" % (os.path.basename(p), e))