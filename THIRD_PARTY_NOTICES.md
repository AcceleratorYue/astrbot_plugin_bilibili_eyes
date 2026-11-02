# 第三方项目与致谢

本项目自身以 MIT License 发布（见 `LICENSE`）。

## 设计与算法参考

### dsh-see-now

- 项目：https://github.com/SAOS-3624/dsh-see-now
- License：Apache License 2.0

增强模式中的“按画面变化选帧、tiers 档位、DP 装箱”思路参考了该项目。
B站之眼使用 Python 重新实现，未直接复制其源码。

### astrbot_plugin_bilibili_watch_Evolution

- 项目：https://github.com/kermond369-nsis/astrbot_plugin_bilibili_watch_Evolution
- ASR / 音频处理链路的思路参考。

## 运行时依赖

以下依赖由 AstrBot 环境提供，本项目不打包其源码：

- AstrBot：插件框架与 Provider 机制，AGPL-3.0-or-later；
- imageio-ffmpeg：ffmpeg 二进制封装；
- Pillow：图像合成。

各依赖的许可证以对应项目发布内容为准。

## B站

本项目使用 B站公开接口，与 B站官方无隶属关系。
