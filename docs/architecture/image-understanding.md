# 文档图片理解与知识引用

## 目标

PDF/PPT 解析出的图片不再只是 Markdown 里的一个链接：

1. 记录图片 MD5、路径、像素面积；
2. 面积达到阈值的图片交给 VLM 解读，提示词可按任务配置；
3. 解读文本参与知识抽取；
4. 知识证据保留源文档路径和图片路径，前端/AI 引用时可渲染原图。

## 数据表

| 表 | 关键字段 | 作用 |
| --- | --- | --- |
| `parsing_document` | `source_md5`、`source_path`、`parsed_md_path`、`progress_percent`、`learned_to_knowledge`、`knowledge_document_id` | 单个文件的解析记录与学习状态 |
| `parsing_image` | `image_md5`、`image_path`、`image_file_path`、`area_px`、`vlm_prompt`、`vlm_content`、`vlm_status`、`learned_to_knowledge` | 单张图片的 VLM 解读与学习状态 |
| `knowledge_document` | `source_md5`、`source_path`、`parsed_md_path` | 知识文档对解析来源的快照 |
| `knowledge_evidence` | `image_id`、`source_path`、`image_path` | 证据到图片/源文件的可引用关联 |

`vlm_status` 取值：

- `succeeded`：VLM 成功返回内容；
- `failed`：图片缺失/解码失败/模型调用失败；
- `skipped_small`：面积低于阈值；
- `disabled`：本次任务关闭了图片理解；
- `pending`：保留给未来异步处理。

## 解析流程

```text
PDF/PPT
  -> OXR 管线切出 Picture block 并写 PNG
  -> understand_result_images
       计算 MD5 / 宽高 / 面积
       面积 >= 阈值 -> model_client.describe_image(prompt)
       解读文本追加到 block.content，供知识抽取读取
  -> result.json / result.md
  -> parsing_image 批量入库
  -> knowledge save_extraction
       证据按 page/block 关联 parsing_image
       写入 knowledge_evidence.image_id/image_path/source_path
       回写 parsing_document / parsing_image 的 learned_to_knowledge
```

VLM 失败不会让文档解析失败：记录为 `failed`，Markdown 和原图仍然保留。

## 配置

全局默认在 `all_ontology/parsing/config/settings.py` 的 `PipelineConfig`：

| 字段 | 默认 |
| --- | --- |
| `image_vlm_enabled` | `true` |
| `image_vlm_min_area_px` | `200000` |
| `image_vlm_prompt` | 中文图片描述提示词 |
| `image_vlm_max_tokens` | `1024` |
| `image_vlm_concurrency` | `2` |

任务级覆盖通过任务的 `options` / `feature_config`：

```json
{
  "image_understanding": true,
  "image_min_area_px": 200000,
  "image_prompt": "请描述这张图片中的表格、指标与结论",
  "image_max_tokens": 1024
}
```

前端解析工作台已提供开关、阈值和提示词输入框。

## API

- `GET /api/parsing/runs/{run_id}`：详情中包含 `images`。
- `GET /api/parsing/runs/{run_id}/images`：单独读取图片记录。
- `GET /api/parsing/capabilities`：返回 `image_understanding` 默认配置。

知识证据接口返回的 `evidence[]` 现在包含 `image_path` 与 `source_path`；
知识网络前端会在证据引用下渲染缩略图。
