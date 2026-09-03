# 🧬 majorbio-omics-download

> 从美吉云（Majorbio）项目中心批量下载组学数据 + scRNA 初步质控 + Word/Excel/PPT 三件套报告，一站式自动化工具。

![python](https://img.shields.io/badge/python-3.8%2B-blue?style=for-the-badge)
![platform](https://img.shields.io/badge/platform-Linux%20%2F%20macOS-orange?style=for-the-badge)
![license](https://img.shields.io/badge/license-MIT-lightgrey?style=for-the-badge)

## 📖 文档导航

| 文档 | 适用人群 | 预计时间 |
|------|---------|:--:|
| **[🌟 新手完全指南](新手完全指南.md)** | 零基础小白（从登录到下载验收） | 20 分钟阅读 + 1 天执行 |
| **[SKILL.md](SKILL.md)** | AI 助手 / 进阶用户（完整流程 + 故障排查） | — |
| **[scripts/majorbio_download.py](scripts/majorbio_download.py)** | 批量下载脚本 | — |
| **[scripts/scRNA_qc_report.py](scripts/scRNA_qc_report.py)** | 质控报告脚本 | — |
| **[小白文档](小白文档/)** | Word/Excel/PPT 三件套（课题组培训） | — |

> ⚠️ **如果你不确定该看哪个** → 直接打开 **[新手完全指南](新手完全指南.md)**，从第一章开始！

## ✨ 特性

- 🔐 SSO 登录 + 图形验证码 OCR（ddddocr）自动识别
- 📂 任务 / 文件遍历（`task/list` + `file/list`）
- ⬇️ 逐文件下载（腾讯 COS 预签名直链，24h 有效）
- 🔁 断点续传（`.part`）与并发下载
- ✅ 完整性金标准校验（MD5 抽样重下 + `gzip -t`）
- 📊 scRNA `metrics_summary` 质控解析 + 4 张统计图
- 📄 Word / Excel / PPT 三件套报告自动生成

## 🏗️ 平台架构

```
登录网关：  uc.majorbio.com      → passport/login（返回 sso token）
数据接口：  apix.majorbio.com    → task/list、file/list、file/download_file
对象存储：  腾讯 COS（S3 兼容）   → file/download_file 返回预签名直链(24h)
```

## 📦 安装

```bash
pip install requests ddddocr pandas matplotlib python-docx openpyxl python-pptx
```

## 🚀 快速开始

### 1. 批量下载

```bash
python scripts/majorbio_download.py \
  --account <账号> --password <密码> \
  --outdir <输出目录>
```

> 🔐 凭据也可用环境变量 `MAJORBIO_ACCOUNT` / `MAJORBIO_PASSWORD` 传入，绝不硬编码。

### 2. 生成质控报告

```bash
python scripts/scRNA_qc_report.py \
  --datadir <下载目录> --outdir <报告目录> --prefix <报告名前缀>
```

## 🧪 实测结果

| 批次 | 文件数 | 数据量 | 结果 |
|------|:--:|:--:|------|
| 4 个测试任务（小鼠/食蟹猴 scRNA + 小鼠 DIA） | 1753 | 13.3 GB | 1752 成功，1 个文件平台锁定 |
| 食蟹猴 20 样本 scRNA | 144 | 1.18 GB | 100% 成功，gzip 60/60 |

## 📂 目录结构

```
majorbio-omics-download/
├── SKILL.md                 ← 完整技能文档（流程 + 故障排查 + 速查表）
├── README.md
├── LICENSE
├── scripts/
│   ├── majorbio_download.py ← 登录 + 遍历 + 逐文件下载
│   └── scRNA_qc_report.py   ← 质控解析 + 图表 + 三件套报告
└── 小白文档/                ← 用户友好三件套
    ├── 美吉组学下载_小白操作手册.docx
    ├── 美吉组学下载_操作表格.xlsx
    └── 美吉组学下载_演示文稿.pptx
```

## ❓ 常见问题

| 现象 | 解决 |
|------|------|
| 下载直链 `400 InvalidArgument` | 预签名 URL 已自带签名，去掉 Authorization 头 |
| `file/download_file` 返回 `12002` | 文件被平台「上锁」，到项目中心 UI 解锁后重试 |
| 验证码识别失败 | ddddocr 命中率约 1/6，脚本自动循环重试 |
| 图表中文豆腐块 | 注册中文字体（见 SKILL.md「图表中文」） |

## 📄 License

[MIT](LICENSE)
