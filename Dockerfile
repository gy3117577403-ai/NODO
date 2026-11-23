# NODO 开发镜像：在官方 Odoo 20.0 社区版镜像上做最小改动。
FROM odoo:20.0-20261112

# 从报价原件渲染指定 PDF 页，用于一键识图。
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils poppler-data \
    && rm -rf /var/lib/apt/lists/*
USER odoo

# 官方镜像（Ubuntu 24.04）已带 Noto CJK 字体，但没有语言标记时，
# 汉字会回退到 Noto Sans CJK JP，按日文字形显示（如「骨」「直」）。
# 设定 fontconfig 默认语言为简体中文，让 PDF 和渲染统一使用 SC 字形，拉丁字母仍用 DejaVu。
ENV FC_LANG=zh-cn

# 构建时校验：中文字体存在，且汉字回退到简体中文字形。任何一项不满足就构建失败。
RUN fc-list :lang=zh | grep -q "Noto Sans CJK SC" \
    && fc-match "sans-serif:charset=4e2d" | grep -q "Noto Sans CJK SC" \
    && fc-match "serif:charset=4e2d" | grep -q "Noto Serif CJK SC" \
    && wkhtmltopdf --version
