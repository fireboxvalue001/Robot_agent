# 实验室机器人动作能力对照

依据用户于2026年10月18日提供的动作清单，逐项补齐能力库。图片中的动作类别用于说明业务用途，界面仍沿用仪器、机器人、环境三大类；本次动作全部归入机器人类。

元操作按“一步动作”登记。本次去重后新增22个单步动作；扶正与回正复用同一个动作，旋开与旋紧、插入与拔出分别登记。12组组合顺序单独保存于 `data/robot-action-templates.json`，组合不是元操作。

本次动作拆解于版本 `1.6.0` 完成，当时共64个条目。当前版本 `1.7.1` 已另增油脂提取29个单步接口，共93个条目，其中55个为单节点条目、38个历史多步条目保留兼容并标记“历史组合”。新增场景见 `docs/LEATHER_EXTRACTION.md`。

## 逐项对应

| 图片中的能力 | 单步动作或组合顺序 | 说明 | 关键控制要求 |
| --- | --- | --- | --- |
| 包络式稳定抓取与搬运 | `envelop_grasp` → `move_grasped_object` → `release_object` | 抓取、搬运和释放是三个独立元操作 | 夹持力可控、不压碎玻璃、不打滑 |
| 指尖精细捏取 | `precision_pinch` | 一个动作，不附加搬运 | 低夹持力、高位置精度、防捏碎变形 |
| 拾取、扶正、对位归位 | `envelop_grasp` → `upright_container` → `move_grasped_object` → `align_object_to_slot` → `release_object` | 每个箭头两侧都是独立元操作 | 微调姿态、轻放对准、不撞击 |
| 旋开／旋紧瓶盖 | `unscrew_cap` 或 `tighten_cap` | 两个独立动作，按意图选其一 | 扭矩感知、防滑牙、防拧碎瓶口 |
| 预压密封再旋紧 | `preload_seal` → `tighten_cap` | 两步，不注册“预压再旋紧”组合能力 | 控制预紧力、避免硬压破损 |
| 持瓶倾斜倾倒试液 | `envelop_grasp` → `move_grasped_object` → `tilt_container` → `pour_liquid` → `upright_container` | 倾斜、液流控制、回正分别调用；回正复用扶正动作 | 限制倾角和速度、防飞溅泼洒 |
| 小幅振荡摇匀 | `hand_shake_sample` | 容器已稳定夹持时的一个持续振荡动作 | 感知液体晃动与动态质心、限制振幅和加速度 |
| 插拔枪头、瓶塞 | `insert_tip_or_stopper` 或 `remove_tip_or_stopper` | 插入、拔出分别登记 | 微调角度、限制插拔力、防断裂 |
| 工具介导操作 | 抓取、搬运分别复用；吸排液用 `aspirate_liquid`、`dispense_liquid`；药勺用 `scoop_sample`、`deposit_solid_sample`；引流用 `guide_liquid` | 组合顺序见 JSON 中的三个工具分支及固体夹持分支 | 工具接触轨迹、清洁、防污染、吸排液体积 |
| 样品分拣与区分 | `identify_sample` → `classify_sample` → `envelop_grasp` → `move_grasped_object` → `release_object` | 对每件样品分别绑定身份、规则和去向 | 识别指定样品、不合格件挑出、保持身份对应 |
| 轻按仪器按键 | `press_instrument_button` | 已定位按键的一次轻按闭环，不包含仪器准备 | 单点轻按、触发后即停，不重复触发 |
| 废样投放 | `envelop_grasp` → `move_grasped_object` → `release_object` | 释放动作指定废样用途并携带外部授权，不重复定义投放组合 | 稳定投放、不中途掉落 |

表中动作 ID 均以 `robot.meta.` 为前缀。组合示例只保存动作引用与顺序，不保存重复的能力定义；不能直接作为带参数的执行链使用。

## 与已有能力的区别

- `robot.meta.mix_sample` 控制摇床或混匀设备；`robot.meta.hand_shake_sample` 是机械臂持瓶振荡，需要动态负载反馈，不能互相直接替换。
- 已有 `robot.meta.transfer_liquid` 为历史组合；其中的吸液、排液节点已提升为独立单步动作。`robot.meta.pour_liquid` 只执行已倾斜容器的液流控制，不再包含抓瓶、对位和回正。定量倾倒须额外提供 `volume_feedback_id`。
- `robot.meta.operate_physical_keyboard` 处理实体键盘输入；仪器面板单点轻按有独立触发与释放要求，因此单独注册。
- 已有 `robot.meta.seal_and_label_sample` 包含密封、贴标和身份绑定，暂为历史组合；本次预压和旋紧分别登记，供后续按需组合。
- 枪头／软塞插拔与螺纹瓶盖旋拧不混用。分拣不合格样品也不代表已获得废弃授权。

## 控制配置与边界

每项动作的 `extensions.supported_objects`、`control_requirements` 和 `control_profile` 保存对象范围、控制要求和待标定配置字段，界面详情中显示对象及关键控制要求，并支持检索。

新增动作要求传入 `control_profile_id`。该编号引用后续由设备控制模块登记的配置，`required_fields` 约定需要的力、扭矩、角度、速度、容差或反馈字段。数值由实际工具、容器和材料标定，本次不填写任意默认值，也不构建第二套能力库。

现有搬运操作保留原输入兼容性及 `grasp_profile_id` 字段；实际包络抓取仍须补充并核验有效配置。

本次每个新元操作都标记 `operation_granularity=single_action`，且只有一个动作节点。Schema 会拒绝带此标记却含多个节点的条目。已存在的抓取、搬运、放置、吸液和排液节点直接复用原节点引用；缺少控制接口的动作标为 `reserved_interface`，所有新增条目均为 `draft`，未声明已实机验证。力反馈、停止和动作结果反馈属于单个闭环动作的控制条件。

废样释放指定 `purpose=waste_deposit` 时，必须携带外部提供的 `disposal_confirmed=true` 和明确废物类别；不代替液体废物倾倒或化学处置。分类动作必须引用外部判定规则和证据，不能自拟合格标准。

当前 AI 场景包括 VD10 单样品检测、定量移液及独立的皮革油脂抽提条件流程；登记能力不自动开放任意动作组合或硬件执行。外部编排器可以通过既有能力查询接口取得新增操作、版本和控制要求。

组合示例可通过 `GET /api/v1/capabilities/action-templates` 查询，与 `meta-operations` 能力查询接口分开。
