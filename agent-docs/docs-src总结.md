# docs-src 文档总结

> 生成日期: 2026年1月13日
> 来源: docs-src 目录

---

## 一、项目规划与未来方向 (Bing.md)

### 1.1 核心发展方向

#### 参数化与动态调整聊天行为
- 提取 `NormalChatInstance` 和 `HeartFlowChatInstance` 中的关键行为参数
- 支持每个 `SubHeartflow` 拥有独立的参数配置，实现"千群千面"
- 动态调整机制：
  - 基于外部反馈：根据用户评价调整回复频率
  - 基于环境分析：根据群消息活跃度自动调整参与度
  - 基于学习：分析历史交互数据优化行为模式
- **目标**：让 Mai 在不同群聊中展现出更适应环境、更个性化的交互风格

#### 动态 Prompt 生成与人格塑造
- 当前 Prompt 相对静态，计划实现动态或半结构化的 Prompt 生成
- Prompt 内容可根据以下因素调整：
  - **人格特质**：通过参数化配置（如友善度、严谨性等）影响 Prompt 的措辞、语气和思考倾向
  - **当前情绪**：将实时情绪状态融入 Prompt
- **目标**：提升 `HeartFlowChatInstance` (HFC) 回复的多样性、一致性和真实感
- **前置**：需要重构 Prompt 构建逻辑，引入 `PromptBuilder` 并提供标准接口

#### 增强工具调用能力 (Enhanced Tool Usage)
- 扩展 `HeartFlowChatInstance` (HFC) 可用的工具集
- 引入"元工具"或分层工具机制，允许 HFC 在需要时访问更强大的工具：
  - 修改自身或其他 `SubHeartflow` 的聊天参数
  - 请求改变 Mai 的全局状态 (`MaiState`)
  - 管理日程或执行更复杂的分析任务
- **目标**：提升 HFC 的自主决策和行动能力

#### 标准化人设生成 (Standardized Persona Generation)
- **目标**：解决手动配置 `人设` 文件缺乏标准、难以全面描述个性的问题
- **方法**：利用 LLM 辅助生成标准化的、结构化的人格**资源包**
- **生成内容**：
  - **相关工具**：该人格倾向于使用的工具或能力
  - **初始记忆/知识库**：定义其背景和知识基础
  - **核心行为模式**：预置一些典型的行为方式
- **实现途径**：
  - 通过与 LLM 的交互式对话来定义和细化人格及其配套资源
  - 让 LLM 分析提供的文本材料（如小说、背景故事）来提取人格特质和相关信息
- **优势**：替代易出错且标准不一的手动配置，生成更丰富、一致、包含配套资源且易于系统理解和应用的人格包

### 1.2 高级功能探索

#### 探索高级记忆检索机制 (GE 系统概念)
- 研究超越简单关键词/近期性检索的记忆模型
- 考虑引入基于事件关联、相对时间线索和绝对时间锚点的检索方式
- 可能涉及设计新的事件表示或记忆结构

#### 基于人格生成预设知识
- 开发利用 LLM 和人格配置生成背景知识的功能
- 这些知识应符合角色的行为风格和可能的经历
- 作为一种"冷启动"或丰富角色深度的方式

#### 工作记忆优化
- 开发更强大的工作记忆系统
- 通过 LLM 进行内容检索
- 创建 play_ground，可以容纳巨量信息，并且十分通用化

---

## 二、贡献指南 (CONTRIBUTE.md)

### 2.1 项目所有权与维护

- **项目创建者**: 千石可乐 SengokuCola
- **开源协议**: GPL3
- **当前维护**: MaiM-with-u 组织
- **维护团队**: 核心开发组、reviewer 和所有贡献者

### 2.2 贡献类型与审核策略

#### 功能新增
- **定义**：涉及新功能添加、架构调整、重要模块重构等
- **要求**：原则上暂不接收，可以发布 issue 提供新功能建议

#### Bug 修复
- **定义**：修复现有功能中的错误，包括非预期行为和运行错误
- **要求**：
  - 由核心组成员或 2 名及以上 reviewer 同时确认才会被合并
  - 需要发布 issue 进行确认
- **关闭条件**：
  - 包含预期行为改动
  - 包含新功能
  - 破坏原有功能
  - 数据库破坏性改动

#### 文档修补
- **定义**：修复现有文档中的错误，提供新的帮助文档
- **要求**：
  - 现需要提交至组织下 docs 仓库
  - 由 reviewer 确认后合并

### 2.3 法律声明

当你为本项目贡献代码/文档时，你必须确认：
1. 你贡献的内容 100% 是由你创作
2. 你对这些内容拥有相应的权利
3. 你贡献的内容将按项目许可协议使用

### 2.4 团队成员

- **核心组成员**: @SengokuCola @tcmofashi @Rikki-Zero
- **reviewer**: 核心组 + MaiBot 主仓库合作者/权限者
- **贡献者**: 所有提交过贡献的用户

---

## 三、LPMM 知识库系统

### 3.1 LPMM 关键参数调节指南 (lpmm_parameters_guide.md)

#### 检索相关参数（影响答案质量与风格）

```toml
qa_relation_search_top_k = 10      # 关系检索TopK
qa_relation_threshold    = 0.5     # 关系阈值
qa_paragraph_search_top_k = 1000   # 段落检索TopK
qa_paragraph_node_weight = 0.05    # 段落节点权重
qa_ent_filter_top_k      = 10      # 实体过滤TopK
qa_ppr_damping           = 0.8     # PPR阻尼系数
qa_res_top_k             = 3       # 最终提供给问答模型的段落数
```

**调参建议**：
- 优先在 `qa_relation_threshold`、`qa_paragraph_node_weight` 上做小幅调整
- 每次调整后，用 `scripts/test_lpmm_retrieval.py` 跑一遍固定问题

#### 性能与硬件相关参数

```toml
embedding_dimension   = 1024  # 嵌入向量维度
max_embedding_workers = 12    # 嵌入/抽取并发线程数
embedding_chunk_size  = 16    # 每批嵌入的条数
info_extraction_workers = 3   # 实体抽取同时执行线程数
enable_ppr            = true  # 是否启用PPR
```

**调参建议**：
- 机器配置弱时，优先调低 `max_embedding_workers`、`embedding_chunk_size`、`info_extraction_workers`
- 或暂时将 `enable_ppr = false`（大幅影响检索效果）

#### 开启/关闭 LPMM 与模式说明

```toml
enable    = true       # 是否开启lpmm知识库
lpmm_mode = "agent"    # 可选 classic / agent
```

- `classic`: 传统模式，仅使用 LPMM 知识库本身
- `agent`: 与新的记忆系统联动，用于更复杂的记忆+知识混合场景

#### 推荐的调参流程

1. 保持默认配置，先跑一轮完整流程
2. 每次只调整一到两个参数
3. 调整后重复同一组测试问题
4. 出现"怎么调都不对"时，恢复默认配置

### 3.2 LPMM 知识库流水线使用指南 (lpmm_pipelines_guide.md)

#### 管理脚本总览：`scripts/lpmm_manager.py`

```bash
python scripts/lpmm_manager.py [--interactive] [-a ACTION] [--non-interactive] [-- ...子脚本参数...]
```

**可选动作**:
- `prepare_raw`: 预处理原始语料
- `info_extract`: 信息抽取
- `import_openie`: 导入 OpenIE 批次
- `delete`: 删除/回滚知识
- `batch_inspect`: 检查指定批次
- `global_inspect`: 全库状态统计
- `refresh`: 刷新 LPMM 磁盘数据到内存
- `test`: 检索效果回归测试
- `full_import`: 一键执行完整流程

#### 典型流水线一：全量导入

```bash
# 交互式
python scripts/lpmm_manager.py --interactive

# 非交互 / CI 友好
python scripts/lpmm_manager.py -a full_import --non-interactive
```

#### 典型流水线二：分步导入

```bash
# 预处理原始语料
python scripts/lpmm_manager.py -a prepare_raw

# 信息抽取
python scripts/lpmm_manager.py -a info_extract
python scripts/lpmm_manager.py -a info_extract --non-interactive

# 导入 OpenIE 批次
python scripts/lpmm_manager.py -a import_openie
python scripts/lpmm_manager.py -a import_openie --non-interactive

# 刷新 LPMM 知识库
python scripts/lpmm_manager.py -a refresh
```

#### 典型流水线三：删除 / 回滚

```bash
# 按哈希文件删除
python scripts/lpmm_manager.py -a delete --non-interactive -- \
  --hash-file data/lpmm_delete_hashes.txt \
  --delete-entities \
  --delete-relations \
  --remove-orphan-entities \
  --max-delete-nodes 2000 \
  --yes

# 按 OpenIE 批次删除
python scripts/lpmm_manager.py -a delete --non-interactive -- \
  --openie-file data/openie/2025-01-01-12-00-openie.json \
  --delete-entities \
  --delete-relations \
  --remove-orphan-entities \
  --yes
```

#### 典型流水线四：自检与状态检查

```bash
# 检查指定批次状态
python scripts/lpmm_manager.py -a batch_inspect -- --openie-file data/openie/xx.json

# 查看整库状态
python scripts/lpmm_manager.py -a global_inspect
```

#### 典型流水线五：检索效果回归测试

```bash
# 使用默认测试用例
python scripts/lpmm_manager.py -a test

# 自定义测试问题
python scripts/lpmm_manager.py -a test -- --query "LPMM 是什么？" \
  --expect-keyword 哈希列表 \
  --expect-keyword 删除脚本
```

### 3.3 LPMM 知识库脚本使用指南 (lpmm_user_guide.md)

#### 需要用到的脚本

**导入相关**:
- `scripts/raw_data_preprocessor.py`: 预处理原始文本
- `scripts/info_extraction.py`: 信息抽取，生成 OpenIE JSON
- `scripts/import_openie.py`: 导入 OpenIE 到向量库与知识图

**删除相关**:
- `scripts/delete_lpmm_items.py`: LPMM 知识库删除入口

**自检相关**:
- `scripts/inspect_lpmm_global.py`: 查看整个知识库的当前状态
- `scripts/inspect_lpmm_batch.py`: 检查某个批次在向量库和知识图中的残留情况
- `scripts/test_lpmm_retrieval.py`: 使用预设问题测试 LPMM 检索能力
- `scripts/refresh_lpmm_knowledge.py`: 手动重新加载到内存

#### LPMM 知识库的初始部署

**第一步：预处理原始文本（拆段 + 去重）**
```bash
.\.venv\Scripts\python.exe scripts/raw_data_preprocessor.py
```

**第二步：进行信息抽取（生成 OpenIE JSON）**
```bash
.\.venv\Scripts\python.exe scripts/info_extraction.py
```

**第三步：导入 OpenIE 数据到 LPMM 知识库**
```bash
.\.venv\Scripts\python.exe scripts/import_openie.py
```

**第四步：全局自检（确认导入成功）**
```bash
.\.venv\Scripts\python.exe scripts/inspect_lpmm_global.py
```

**第五步：用脚本测试 LPMM 检索效果（可选但推荐）**
```bash
.\.venv\Scripts\python.exe scripts/test_lpmm_retrieval.py
```

#### 安全删除知识的几种方式

**按批次删除（推荐：整批回滚）**
```bash
# 检查批次状态
.\.venv\Scripts\python.exe scripts/inspect_lpmm_batch.py ^
  --openie-file data/openie/<OPENIE>.json

# 按批次删除
.\.venv\Scripts\python.exe scripts/delete_lpmm_items.py ^
  --openie-file data/openie/<OPENIE>.json ^
  --delete-entities --delete-relations --remove-orphan-entities
```

**按原始文本段落删除（精确定位某一段）**
```bash
.\.venv\Scripts\python.exe scripts/delete_lpmm_items.py ^
  --raw-file data/lpmm_raw_data/lpmm_large_sample.txt ^
  --raw-index 2
```

**按哈希列表删除（进阶用法）**
```bash
.\.venv\Scripts\python.exe scripts/delete_lpmm_items.py ^
  --hash-file data/openie/lpmm_delete_test_hashes.txt
```

**按关键字模糊搜索删除（对非技术用户最友好）**
```bash
.\.venv\Scripts\python.exe scripts/delete_lpmm_items.py ^
  --search-text "近义词扩展" ^
  --search-limit 5
```

#### 自检：如何确认导入 / 删除是否"生效"

**全局状态检查**
```bash
.\.venv\Scripts\python.exe scripts/inspect_lpmm_global.py
```

**某个批次的局部状态**
```bash
.\.venv\Scripts\python.exe scripts/inspect_lpmm_batch.py ^
  --openie-file data/openie/<OPENIE>.json
```

**检索效果回归测试**
```bash
.\.venv\Scripts\python.exe scripts/test_lpmm_retrieval.py
```

**一键刷新（可选）**
```bash
.\.venv\Scripts\python.exe scripts/refresh_lpmm_knowledge.py
```

#### 常见提示与注意事项

1. **看到"网络错误(可重试)"需要担心吗？**
   - 不需要。脚本在自动处理网络抖动，多数情况下会在重试后成功返回结果。

2. **删除操作会不会"一删全没"？**
   - 不会直接"一删全没"，但建议在大规模删除前备份 `data/embedding` 和 `data/rag`。

3. **可以多次导入吗？需要先清空吗？**
   - 可以多次导入，系统会根据段落内容的哈希做去重。

4. **LPMM 开关在哪里？**
   - 配置文件：`config/bot_config.toml`
   - 小节：`[lpmm_knowledge]`
   - 其中有 `enable = true/false` 开关

---

## 四、插件开发文档 (plugins/)

### 4.1 插件开发文档索引 (index.md)

#### 新手入门
- [📖 快速开始指南](quick-start.md) - 快速创建你的第一个插件

#### 组件功能详解
- [🧱 Action组件详解](action-components.md) - 掌握最核心的Action组件
- [💻 Command组件详解](command-components.md) - 学习直接响应命令的组件
- [🔧 Tool组件详解](tool-components.md) - 了解如何扩展信息获取能力
- [⚙️ 配置文件系统指南](configuration-guide.md) - 学会使用自动生成的插件配置文件
- [📄 Manifest系统指南](manifest-guide.md) - 了解插件元数据管理和配置架构

#### Command vs Action 选择指南

**使用Command的场景**:
- ✅ 用户需要明确调用特定功能
- ✅ 需要精确的参数控制
- ✅ 管理和配置操作
- ✅ 查询和信息显示
- ✅ 系统维护命令

**使用Action的场景**:
- ✅ 增强麦麦的智能行为
- ✅ 根据上下文自动触发
- ✅ 情绪和表情表达
- ✅ 智能建议和帮助
- ✅ 随机化的互动

#### API 浏览

**消息发送与处理API**:
- [📤 发送API](api/send-api.md) - 各种类型消息发送接口
- [消息API](api/message-api.md) - 消息获取，消息构建，消息查询接口
- [聊天流API](api/chat-api.md) - 聊天流管理和查询接口

**AI与生成API**:
- [LLM API](api/llm-api.md) - 大语言模型交互接口
- [✨ 回复生成器API](api/generator-api.md) - 智能回复生成接口

**表情包API**:
- [😊 表情包API](api/emoji-api.md) - 表情包选择和管理接口

**关系系统API**:
- [人物信息API](api/person-api.md) - 用户信息，处理麦麦认识的人和关系的接口

**数据与配置API**:
- [🗄️ 数据库API](api/database-api.md) - 数据库操作接口
- [⚙️ 配置API](api/config-api.md) - 配置读取和用户信息接口

**插件和组件管理API**:
- [🔌 插件API](api/plugin-manage-api.md) - 插件加载和管理接口
- [🧩 组件API](api/component-manage-api.md) - 组件注册和管理接口

**日志API**:
- [📜 日志API](api/logging-api.md) - logger实例获取接口

**工具API**:
- [🔧 工具API](api/tool-api.md) - tool获取接口

### 4.2 快速开始指南 (quick-start.md)

#### 创建最简单的插件

```python
from typing import List, Tuple, Type
from src.plugin_system import BasePlugin, register_plugin, ComponentInfo

@register_plugin
class HelloWorldPlugin(BasePlugin):
    """Hello World插件 - 你的第一个MaiCore插件"""

    plugin_name = "hello_world_plugin"
    enable_plugin = True
    dependencies = []
    python_dependencies = []
    config_file_name = "config.toml"
    config_schema = {}

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return []
```

#### 添加第一个功能：问候Action

```python
from typing import Tuple
from src.plugin_system import BaseAction, ActionActivationType

class HelloAction(BaseAction):
    """问候Action - 简单的问候动作"""

    action_name = "hello_greeting"
    action_description = "向用户发送问候消息"
    activation_type = ActionActivationType.ALWAYS

    action_parameters = {"greeting_message": "要发送的问候消息"}
    action_require = ["需要发送友好问候时使用", "当有人向你问好时使用", "当你遇见没有见过的人时使用"]
    associated_types = ["text"]

    async def execute(self) -> Tuple[bool, str]:
        greeting_message = self.action_data.get("greeting_message", "")
        base_message = self.get_config("greeting.message", "嗨！很开心见到你！😊")
        message = base_message + greeting_message
        await self.send_text(message)

        return True, "发送了问候消息"
```

#### 添加第二个功能：时间查询Command

```python
import datetime
from typing import Tuple, Optional
from src.plugin_system import BaseCommand

class TimeCommand(BaseCommand):
    """时间查询Command - 响应/time命令"""

    command_name = "time"
    command_description = "查询当前时间"
    command_pattern = r"^/time$"

    async def execute(self) -> Tuple[bool, Optional[str], int]:
        time_format: str = "%Y-%m-%d %H:%M:%S"
        now = datetime.datetime.now()
        time_str = now.strftime(time_format)

        message = f"⏰ 当前时间：{time_str}"
        await self.send_text(message)

        return True, f"显示了当前时间: {time_str}", 1
```

#### 添加配置文件

```python
from src.plugin_system import ConfigField

config_schema: dict = {
    "plugin": {
        "name": ConfigField(type=str, default="hello_world_plugin", description="插件名称"),
        "version": ConfigField(type=str, default="1.0.0", description="插件版本"),
        "enabled": ConfigField(type=bool, default=False, description="是否启用插件"),
    },
    "greeting": {
        "message": ConfigField(type=str, default="嗨！很开心见到你！😊", description="默认问候消息"),
        "enable_emoji": ConfigField(type=bool, default=True, description="是否启用表情符号"),
    },
    "time": {"format": ConfigField(type=str, default="%Y-%m-%d %H:%M:%S", description="时间显示格式")},
}
```

### 4.3 插件开发指南 (development-guide.md)

#### 核心组件

**Command（命令组件）**
- 用于处理用户输入的命令
- 通过正则表达式匹配用户输入
- 返回值: `(是否执行成功, 可选的回复消息, 拦截消息力度)`

**Action（动作组件）**
- MaiBot 的核心创新
- 允许 LLM 在聊天中执行特定动作
- 激活类型: ALWAYS, NEVER, KEYWORD, RANDOM
- 返回值: `(是否执行成功, 回复文本)`

**EventHandler（事件处理器）**
- 监听系统事件
- 事件类型: ON_START, ON_STOP, ON_MESSAGE, ON_PLAN, POST_LLM, AFTER_LLM, POST_SEND
- 返回值: `(是否执行成功, 是否继续处理, 可选的返回消息, 可选的自定义结果, 可选的修改后消息)`

**Tool（工具组件）**
- 为 LLM 提供可调用的工具函数
- 参数类型: STRING, INTEGER, FLOAT, BOOLEAN, ARRAY, OBJECT
- 返回值: 工具执行结果字典

#### 插件清单 (_manifest.json)

```json
{
  "manifest_version": 2,
  "id": "author.plugin_name",
  "name": "插件名称",
  "version": "1.0.0",
  "description": "插件描述",
  "author": {
    "name": "作者名",
    "url": "https://github.com/author"
  },
  "license": "GPL-v3.0-or-later",
  "host_application": {
    "min_version": "0.12.0",
    "max_version": ""
  },
  "keywords": ["keyword1", "keyword2"],
  "categories": ["Utility", "System"],
  "default_locale": "zh-CN",
  "supported_locales": ["zh-CN", "en", "ja", "ko"],
  "plugin_info": {
    "is_built_in": false,
    "plugin_type": "utility",
    "components": [
      {
        "type": "command",
        "name": "info",
        "description": "获取系统信息",
        "pattern": "/info"
      }
    ],
    "features": [
      "功能1",
      "功能2"
    ],
    "configuration": {
      "auto_generate_config": true,
      "config_file": "config.toml"
    }
  },
  "changelog": {
    "1.0.0": ["初始版本发布"]
  }
}
```

#### 配置系统

**ConfigField 属性**:
- `type`: 字段类型 (str, int, float, bool, list, dict)
- `default`: 默认值
- `description`: 字段描述
- `input_type`: 输入控件类型 (text, password, number, switch, select, etc.)
- `required`: 是否必填
- `choices`: 可选值列表
- `min/max`: 数值范围
- `placeholder`: 输入框占位符
- `hint`: 提示文字
- `disabled`: 是否禁用
- `hidden`: 是否隐藏

#### i18n 国际化支持

**翻译文件格式**:
```json
{
  "section_system": "系统信息",
  "section_hardware": "硬件状态",
  "label_cpu_usage": "CPU 已使用",
  "label_memory": "内存占用",
  "error_psutil_missing": "错误：未安装 psutil 库。",
  "success_sent": "成功发送状态图"
}
```

**i18n 管理器**:
```python
class I18nManager:
    """国际化管理器"""
    
    _instance = None
    _translations: Dict[str, Dict[str, str]] = {}
    
    def get(self, key: str, locale: str = "zh-CN") -> str:
        """获取翻译文本"""
        try:
            return self._translations.get(locale, {}).get(
                key, 
                self._translations.get("zh-CN", {}).get(key, key)
            )
        except Exception:
            return key

i18n = I18nManager()
```

#### 最佳实践

**错误处理**:
```python
async def execute(self) -> Tuple[bool, Optional[str], int]:
    try:
        result = await self._do_something()
        return True, "操作成功", 1
    except ValueError as e:
        logger.error(f"参数错误: {e}")
        return False, f"参数错误: {str(e)}", 0
    except Exception as e:
        logger.exception(f"未知错误: {e}")
        return False, "操作失败，请稍后重试", 0
```

**异步优先**:
```python
# 错误示例
def get_data():
    response = requests.get(url)  # 同步请求
    return response.json()

# 正确示例
import aiohttp

async def get_data():
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()
```

**类型注解**:
```python
from typing import Tuple, Optional, List, Dict, Any

async def complex_function(
    user_id: str,
    options: Optional[Dict[str, Any]] = None
) -> Tuple[bool, Optional[str], List[str]]:
    """函数描述"""
    pass
```

**插件卸载清理**:
```python
class MyPlugin(BasePlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cleanup_tasks = []
    
    def on_unload(self):
        """插件卸载时清理资源"""
        for task in self._cleanup_tasks:
            task.cancel()
        logger.info("插件资源已清理")
```

### 4.4 Manifest系统指南 (manifest-guide.md)

#### 配置架构：Manifest与Config的职责分离

- **`_manifest.json`** - 插件的**静态元数据**
  - 插件身份信息（名称、版本、描述）
  - 开发者信息（作者、许可证、仓库）
  - 系统信息（兼容性、组件列表、分类）

- **`config.toml`** - 插件的**运行时配置**
  - 启用状态 (`enabled`)
  - 功能参数配置
  - 用户可调整的行为设置

#### Manifest文件结构

**必需字段**:
```json
{
  "manifest_version": 1,
  "name": "插件显示名称",
  "version": "1.0.0",
  "description": "插件功能描述",
  "author": {
    "name": "作者名称"
  }
}
```

**可选字段**:
```json
{
  "license": "MIT",
  "host_application": {
    "min_version": "1.0.0",
    "max_version": "4.0.0"
  },
  "homepage_url": "https://github.com/your-repo",
  "repository_url": "https://github.com/your-repo",
  "keywords": ["关键词1", "关键词2"],
  "categories": ["分类1", "分类2"],
  "default_locale": "zh-CN",
  "locales_path": "_locales",
  "plugin_info": {
    "is_built_in": false,
    "plugin_type": "general",
    "components": [
      {
        "type": "action",
        "name": "组件名称",
        "description": "组件描述"
      }
    ]
  }
}
```

#### 管理工具

```bash
# 扫描缺少manifest的插件
python scripts/manifest_tool.py scan src/plugins

# 为插件创建最小化manifest文件
python scripts/manifest_tool.py create-minimal src/plugins/my_plugin --name "我的插件" --author "作者"

# 为插件创建完整manifest模板
python scripts/manifest_tool.py create-complete src/plugins/my_plugin --name "我的插件"

# 验证manifest文件
python scripts/manifest_tool.py validate src/plugins/my_plugin
```

#### 注意事项

1. **强制要求**：所有插件必须包含`_manifest.json`文件，否则无法加载
2. **编码格式**：manifest文件必须使用UTF-8编码
3. **JSON格式**：文件必须是有效的JSON格式
4. **必需字段**：`manifest_version`、`name`、`version`、`description`、`author.name`是必需的
5. **版本兼容**：当前只支持`manifest_version = 1`

---

## 五、总结

docs-src 目录包含了 MaiBot 项目的完整开发文档，涵盖：

1. **项目规划**: Bing.md - 项目的未来发展方向和高级功能探索
2. **贡献指南**: CONTRIBUTE.md - 如何为项目做贡献，包括贡献类型、审核策略和法律声明
3. **LPMM 知识库系统**:
   - 参数调节指南 - 详细的参数说明和调参建议
   - 流水线使用指南 - 完整的导入/删除/测试流程
   - 脚本使用指南 - 面向零基础用户的使用说明
4. **插件开发文档**:
   - 索引 - 所有插件开发文档的导航
   - 快速开始 - 创建第一个插件的完整教程
   - 开发指南 - 插件系统的完整架构和最佳实践
   - Manifest指南 - 插件元数据管理系统

这些文档为开发者提供了从入门到精通的完整指南，涵盖了项目的各个方面。