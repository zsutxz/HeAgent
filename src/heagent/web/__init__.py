"""HeAgent 内置网页资源包（Epic 49）。

本包**只有静态资源**，没有运行时代码：``index.html`` / ``app.js`` / ``styles.css`` 随
``wheel`` 分发，由 :mod:`heagent.network.http_server` 经
``importlib.resources.files("heagent.web")`` 读取（AD-11 规定的**唯一**查找方式）——
不用 ``__file__`` 相对路径、更不用开发机绝对路径。

实现约束（改这里前先读 ``docs/frame.md`` 4.17）：

- 页面与 ``/api/*`` **同源**（同一个 ASGI app），因此不引入 CORS 配置；
- 页面**不加载任何第三方脚本/字体/图片**，并遵守严格的 CSP（无非内联脚本、无非内联样式），
  故所有行为在 ``app.js``、所有样式在 ``styles.css``，HTML 里不出现 ``<script>`` 正文或
  ``style=`` 属性；
- 提示词与 Agent 输出一律**按纯文本渲染**（``textContent`` / ``createTextNode``），
  绝不写 ``innerHTML``——Agent 输出是不可信内容。

``tests/test_architecture_contracts.py`` 断言本包不导入任何 ``heagent`` 运行时模块。
"""

__all__: list[str] = []
