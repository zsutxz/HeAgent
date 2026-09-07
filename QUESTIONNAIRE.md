# Questionnaire

name: game-product-decisions
applies_when: 游戏|game
include_in_step: step-01-analyze-requirements.md

### Q1 对手类型
id: opponent_type
options: A 本地双人|B 人机|C 两者

### Q2 平台
id: platform
options: 桌面（操作系统）|浏览器|终端|其他

### Q3 规则
id: rules
options: 标准完整规则|简化 MVP

### Q4 首版附加能力
id: launch_features
options: 无|悔棋|保存/继续|计时|合法落点提示|走子记录|重新开始

### Q5 基础单难度是否可接受
id: ai_single_difficulty
when: opponent_type=B 人机|C 两者

### Q6 电脑每步最长思考时间（秒）
id: ai_think_seconds
type: number
minimum: 0
when: opponent_type=B 人机|C 两者
