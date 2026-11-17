# 第三方声明

## Odoo 社区版

NODO 基于 Odoo 社区版 20.0 二次开发。Odoo 社区版由 Odoo S.A. 以 GNU LGPL v3 许可发布，许可证随官方源码提供。NODO 不修改 Odoo 核心代码，所有定制在 `addons/` 下的独立模块中完成。

## Solid Glass

NODO 后台的材质规则（实心玻璃，不透明版）借鉴了 Solid Glass 的设计规则和部分阴影、透明度参数：质感在边缘、深度靠厚度、唯一状态。NODO 没有使用它的组件代码，按 Odoo 的界面结构重新实现，见 `addons/nodo_base/static/src/scss/primary_variables.scss` 与 `material.scss`。

- 项目：https://github.com/deeplethe/solid-glass
- 许可：MIT License

> MIT License
>
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
> associated documentation files (the "Software"), to deal in the Software without restriction,
> including without limitation the rights to use, copy, modify, merge, publish, distribute,
> sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or
> substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
> NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
> NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
> DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT
> OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## 图标与字体

- 效果图中使用的 Tabler 图标（MIT）未打包进产品。
- 产品界面使用系统字体（微软雅黑、苹方），PDF 使用容器内的 Noto CJK（SIL Open Font License）。
