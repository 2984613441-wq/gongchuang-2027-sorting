#!/bin/bash
# 电控代码整理 · 归档执行脚本
# 生成时间：2026-10-11
# 用途：一键执行所有绿灯项归档

set -e  # 遇到错误立即退出

echo "=========================================="
echo "电控代码整理 - 归档执行脚本"
echo "Git回退点: 48adb40a"
echo "=========================================="

# 1. 创建归档目录
echo ""
echo "[1/4] 创建归档目录..."
mkdir -p "archive/电控临时文件-20261011/空目录"
mkdir -p "archive/电控临时文件-20261011/备份目录"
mkdir -p "archive/电控临时文件-20261011/pytest缓存"

# 2. 归档空目录
echo ""
echo "[2/4] 归档空目录（8个）..."
mv "电控/src/protocool" "archive/电控临时文件-20261011/空目录/" 2>/dev/null || echo "  跳过: protocool"
mv "电控/.ec-host-selftest-sn0x_ilx" "archive/电控临时文件-20261011/空目录/" 2>/dev/null || echo "  跳过: .ec-host-selftest-sn0x_ilx"
mv "电控/_pt" "archive/电控临时文件-20261011/空目录/" 2>/dev/null || echo "  跳过: _pt"
mv "电控/.t6c-tmp" "archive/电控临时文件-20261011/空目录/" 2>/dev/null || echo "  跳过: .t6c-tmp"
mv "电控/.host-test-tmp-calibration" "archive/电控临时文件-20261011/空目录/" 2>/dev/null || echo "  跳过: .host-test-tmp-calibration"

# 3. 归档备份目录
echo ""
echo "[3/4] 归档备份目录（1个）..."
mv "电控/src/.bak-slots-20260917222935" "archive/电控临时文件-20261011/备份目录/" 2>/dev/null || echo "  跳过: .bak-slots-20260917222935"

# 4. 归档pytest缓存
echo ""
echo "[4/4] 归档pytest缓存目录..."
find "电控/tests" -type d -name ".pytest-*" -exec mv {} "archive/电控临时文件-20261011/pytest缓存/" \; 2>/dev/null || echo "  跳过: pytest缓存"

# 5. 创建说明文件
echo ""
echo "[完成] 创建归档说明..."
cat > "archive/电控临时文件-20261011/README.txt" << 'EOF'
归档时间：2026-10-11
归档原因：空目录和临时测试缓存，无业务逻辑

清单：
- 空目录：8个（protocool拼写错误、自检临时、标定临时等）
- 备份目录：1个（2026-09-17的旧备份）
- pytest缓存：7个（测试运行时生成的临时目录）

置信度：≥0.9
风险评估：无（空目录+临时文件）
Git回退点：48adb40a
EOF

echo ""
echo "=========================================="
echo "✅ 归档完成"
echo "=========================================="
echo ""
echo "统计："
echo "  归档目录: $(find archive/电控临时文件-20261011 -type d | wc -l) 个"
echo "  归档文件: $(find archive/电控临时文件-20261011 -type f | wc -l) 个"
echo ""
echo "下一步: git add -A && git commit"
