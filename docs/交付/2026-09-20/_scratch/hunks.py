import difflib, re
A = r"电控\deploy\run_chain.py"
B = r"docs\交付\2026-09-20\_scratch\run_chain.pi.py"
a = open(A, encoding="utf-8").read().splitlines()
b = open(B, encoding="utf-8").read().splitlines()
def owner(lines, idx):
    for i in range(idx, -1, -1):
        m = re.match(r"^(def |class )(\w+)", lines[i])
        if m: return m.group(2)
    return "<module>"
sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
ops = [o for o in sm.get_opcodes() if o[0] != "equal"]
for k, (tag, i1, i2, j1, j2) in enumerate(ops, 1):
    print("--- 差异块 %d : %s ---" % (k, tag))
    print("  本地行 %d-%d (%d行)  [函数/类: %s]" % (i1+1, i2, i2-i1, owner(a, max(i1-1,0))))
    print("  树莓派行 %d-%d (%d行)  [函数/类: %s]" % (j1+1, j2, j2-j1, owner(b, max(j1-1,0))))
    for L in a[i1:i2][:6]:  print("    LOCAL | " + L[:110])
    for L in b[j1:j2][:6]:  print("    PI    | " + L[:110])
    print()
