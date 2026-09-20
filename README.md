# 档口开单系统

本机 API + SQLite + 普通浏览器界面，内置 RapidOCR / ONNX Runtime CPU 离线文字识别。目标 Windows 10/11 x64；首个本地试用版本 0.1.0，无在线账号、云数据库或付费接口。

## 开发运行

使用 Python 3.12 x64，在本目录建立 `.venv`，执行：

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
node build_frontend.cjs
./.venv/Scripts/python.exe app.py
```

`build_frontend.cjs` 从不含用户订单照片的 `ui-base.html` 提取已确认样式和交互，替换演示功能为 `frontend-live.js` 中的真实接口。最终运行只使用 `web/`，不读取原型或联网资源。

数据首次启动时可选择存储文件夹；未选择时默认 `%LOCALAPPDATA%/HuoYouShu`，实际目录会显示在商品资料库页面。调试可加 `--data-dir ./test-data --no-browser --port 18763`。仅监听本机，随机本机会话，API 修改请求校验来源和自定义请求头。程序退出可在页面操作。

## 验证与构建

```powershell
./.venv/Scripts/python.exe -m unittest test_local -v
./build.ps1
```

`test_local.py` 包含 9 项业务测试。前端先通过 `node build_frontend.cjs` 生成再运行测试。首版交付还在本机实际执行了浏览器录入、导入、导出、识别及冻结程序重启验证。

构建脚本生成 `dist/档口开单系统/档口开单系统.exe` 与上一级 `outputs/档口开单系统-0.1.0-Windows-x64.zip`。最终只打包冻结程序、使用说明和依赖许可，不含测试数据库、用户照片、厂家资料或开发环境。依赖版本已锁定；首次构建需要联网安装依赖，用户运行不需要。

## 当前边界

- 尚未收到实际厂家 Excel 或指定报货模板，当前为可映射字段的通用导入与报货单。
- 离线文字识别不能保证手写订单准确。所有识别行须人工核对，无法匹配时手动选择，不能确定的单位不猜测。
- 用户已确认先交付本地试用包。源码私有仓库为 `Oujiang-77/yiwu-counter`；自动更新发布源与安装流程暂未启用，仓库创建不代表自动更新已实现。完整新包替换程序，数据独立保存。
- 备份含数据库、图片和草稿；导出文件需另存，恢复后历史记录可能指向尚未拷回的文件。
- 单人单机使用，不能让多个设备共享 SQLite 文件。不含删除商品、多账号权限、库存和财务记账功能。
- 尚未在朋友的 Windows 10 电脑验收。运行时与模型已经随包提供，但仍需实际目标电脑验证。
