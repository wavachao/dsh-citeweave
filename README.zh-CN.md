# CiteWeave for DeepSeek Harness

为 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 提供网页检索与有来源的配图。

[![CI](https://github.com/wavachao/dsh-citeweave/actions/workflows/ci.yml/badge.svg)](https://github.com/wavachao/dsh-citeweave/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-235c45)](LICENSE)

[English](README.md) · [后端部署](https://github.com/wavachao/dsh-citeweave/tree/main/backend) · [接口与配置](docs/reference.md) · [版本发布](https://github.com/wavachao/dsh-citeweave/releases)

CiteWeave 检索网页证据，评估候选图片，将来源链接和配图交给 Harness。当前配置的 DeepSeek 模型生成最终回答，在相关解释旁展示图片。

本仓库包含 Harness 插件及其 Python 后端。后端通过 vLLM 运行 Qwen3.5-9B，嵌入与重排序使用 CPU，检索任务由 Celery、Redis 和 PostgreSQL 管理。共享显卡时，模型按需启动，空闲后释放显存。

## 效果示例

**地质**：结合美国国家公园管理局地质图，解释大峡谷岩层。

![大峡谷地层回答与来源示意图](docs/images/geography.png)

**生物**：结合照片说明帝王蝶翅膀纹路与识别特征。

![帝王蝶识别回答与来源照片](docs/images/biology.png)

**工程**：结合金门大桥照片，解释悬索桥的荷载传递路径。

![桥梁工程回答与来源照片](docs/images/engineering.png)

[图片署名](docs/images/README.md)

## 安装

### 后端

从 [backend/](https://github.com/wavachao/dsh-citeweave/tree/main/backend) 部署服务。参考配置为 Linux、Python 3.12、Docker、RTX 3060 12 GB 和 32 GB 内存。

```sh
git clone https://github.com/wavachao/dsh-citeweave.git
cd dsh-citeweave/backend
```

按照[部署指南](https://github.com/wavachao/dsh-citeweave/blob/main/backend/README.md)安装依赖、下载模型并启动服务。

### Harness 插件

在 Harness Desktop 或 Web 中打开**插件 → 添加插件**，输入：

```text
github:wavachao/dsh-citeweave#v0.5.1
```

打开**已安装插件 → CiteWeave → 配置 CiteWeave 图文检索**，填写后端地址和工作区访问令牌，保存即可。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `endpoint` | `http://127.0.0.1:8765` | 后端地址，也可使用 `CITEWEAVE_ENDPOINT`。 |
| `accessToken` | 空 | 工作区令牌，也可使用 `CITEWEAVE_ACCESS_TOKEN`。 |
| `timeoutMs` | `300000` | 工具调用超时，单位为毫秒。 |
| `maxImages` | `3` | 单次检索最多图片数，范围 1–8。 |

令牌输入框留空会保留已保存值。命令行安装与环境变量配置见[参考文档](docs/reference.md)。

## 使用

> 解释埃拉托色尼如何测量地球周长，配上示意图并注明来源。

> 对比悬索桥与斜拉桥，用照片展示它们的结构差异。

Harness 调用 `citeweave_search`，根据证据组织回答，通过原生附件存储嵌入图片。工具支持自动搜索、最多五个指定网页、图片验证和缓存刷新，详见[工具参考](docs/reference.md#citeweave_search)。

后端不可用时，Harness 继续回答，不采用该次工具结果。检索覆盖和图片可用性取决于来源网站。

## 评测

对比脚本、回答样本与结果见 [benchmarks](https://github.com/wavachao/dsh-citeweave/tree/main/benchmarks)。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| [index.js](index.js)、[client.js](client.js) | Harness 工具与配置界面 |
| [backend/src/citeweave/](https://github.com/wavachao/dsh-citeweave/tree/main/backend/src/citeweave) | 检索 API、任务处理、排序与模型生命周期 |
| [backend/](https://github.com/wavachao/dsh-citeweave/tree/main/backend) | Python 软件包、部署配置与测试 |
| [benchmarks/](https://github.com/wavachao/dsh-citeweave/tree/main/benchmarks) | Harness 对比与测量记录 |

插件适配 Harness `0.2.1-rc.2`，需要 Node.js 24 或更新版本。插件与后端源码统一发布；安装包包含 Harness 插件，后端使用对应的仓库版本标签部署。

## 参与贡献

开发与测试见 [CONTRIBUTING.md](https://github.com/wavachao/dsh-citeweave/blob/main/CONTRIBUTING.md)。问题反馈请使用 [GitHub Issues](https://github.com/wavachao/dsh-citeweave/issues)，安全问题见 [SECURITY.md](https://github.com/wavachao/dsh-citeweave/blob/main/SECURITY.md)。

## 许可证

[MIT](LICENSE)。基于 [CiteWeave](https://github.com/wavachao/citeweave)。模型与第三方资源许可见 [backend/THIRD_PARTY.md](https://github.com/wavachao/dsh-citeweave/blob/main/backend/THIRD_PARTY.md)，检索图片保留原始许可证。
