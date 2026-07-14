"""Web 套壳后端桥接层。

三层解耦架构中的 ②：负责数据聚合、封面提色、配置读写，
通过 pywebview 的 js_api 暴露给前端。数据源层 (get_music_powershell.py)
和前端表现层都不依赖本层的内部实现，只依赖统一数据契约 state。
"""
