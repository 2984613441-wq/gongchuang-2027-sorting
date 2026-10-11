import difflib, io, os, re, sys
a = open(r"电控\deploy\run_chain.py", encoding="utf-8").read().splitlines()
b = open(r"docs\交付\2026-09-20\_scratch\run_chain.pi.py", encoding="utf-8").read().splitlines()
sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
ops = [o for o in sm.get_opcodes() if o[0] != "equal"]
print("本地(新)行数=%d  树莓派(旧)行数=%d  差异块=%d" % (len(a), len(b), len(ops)))
add = sum(o[4]-o[3] for o in ops); dele = sum(o[2]-o[1] for o in ops)
print("本地独有行=%d  树莓派独有行=%d" % (add, dele))
print()
# 找出被改动/新增/删除的顶层 def / class
pat = re.compile(r"^(def |class |    def )")
def names(lines, op):
    out=[]
    for i in range(op[1], op[2]):
        m = pat.match(lines[i])
        if m: out.append(lines[i].strip())
    return out
print("== 本地新增或改名的 def/class ==")
s=set()
for o in ops:
    for n in names(a,o): s.add(n)
for n in sorted(s): print("  +", n)
print()
print("== 树莓派独有（本地已删）的 def/class ==")
s2=set()
for o in ops:
    for n in names(b,o): s2.add(n)
for n in sorted(s2): print("  -", n)
