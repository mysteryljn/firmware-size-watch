# firmware-size-watch

**把 GNU ld map 变成 ROM/RAM 预算检查和可分享的增长报告。**

`.data` 在运行时占 RAM、在加载镜像中占 Flash；`.bss` 占运行内存而不对应初始化镜像字节。本工具分别处理 VMA/LMA，并避免把 output section 和缩进的 input subsection 重复计数。纯软件、无第三方运行依赖、不需要目标硬件。

```sh
git clone https://github.com/mysteryljn/firmware-size-watch.git
cd firmware-size-watch
python -m pip install .
python -m firmware_size_watch demo --output report.html
```

安装后可在任意目录运行演示。HTML 无外部资源；合成例子中 FLASH 从 304 增长到 384 字节，RAM 从 144 增长到 176 字节。示例 map 是人工编写的数据，不宣称来自车厂或实际编译器输出。

```sh
firmware-size-watch check firmware.map --budget FLASH=60000 --budget RAM=12000 --output memory.html
firmware-size-watch compare old.map new.map --max-growth 1024 --format json
```

正常通过返回 0，预算/增长/地址范围问题返回 1，非法输入或无法输出返回 2。`--budget` 支持十进制和 `0x` 十六进制字节数，区域名拼错会直接报错；`--max-growth` 限制每个区域的绝对增长。

`used` 是占用地址区间的并集，`span` 包含区域起点至最高地址之间的空洞。预算检查 used，不代表连续可用空间。常规 `.bss/.sbss/.noinit/.stack/.heap` 名称按 NOLOAD 处理；自定义 NOLOAD 必须用 `--noload-section '.retained*'` 声明，因为 map 本身没有完整 ELF 类型信息。

首版仅支持有明确、互不重叠 MEMORY 区域的常见 GNU ld map 格式，不支持 IAR/Keil/TASKING，不声称是所有工具链的通用解析器。贡献归因到 output section，不细分对象文件。Bloaty 已有尺寸 diff，本项目的价值是 MCU 区域策略、预算门禁和离线报告。

仓库提供 C 与链接脚本。测试在有 GNU gcc/ld/readelf 时真实生成 map 并与 ELF section 尺寸对照；没有工具链时明确跳过该项。更多边界、命令和限制见 [英文 README](README.md)。
