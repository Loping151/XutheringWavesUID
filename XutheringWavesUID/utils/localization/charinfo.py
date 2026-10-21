from . import _register

_register({
    # 用户信息
    "联觉等级": {
        "cht": "聯覺等級",
        "en": "Union Level",
        "jp": "ユニオンレベル",
        "kr": "연각 레벨",
    },
    "索拉等阶": {
        "cht": "索拉等階",
        "en": "SOL3 Phase",
        "jp": "ソラランク",
        "kr": "솔라리스 랭크",
    },
    # 声骸评分区
    "声骸评级": {
        "cht": "聲骸評級",
        "en": "Echo Rating",
        "jp": "音骸レーティング",
        "kr": "음해 등급",
    },
    "声骸评分": {
        "cht": "聲骸評分",
        "en": "Echo Score",
        "jp": "音骸スコア",
        "kr": "음해 점수",
    },
    "综合评分": {
        "cht": "綜合評分",
        "en": "Overall Score",
        "jp": "総合スコア",
        "kr": "종합 점수",
    },
    "暂无": {
        "cht": "暫無",
        "en": "N/A",
        "jp": "なし",
        "kr": "없음",
    },
    "分": {
        "cht": "分",
        "en": "pts",
        "jp": "点",
        "kr": "점",
    },
    "评分模板": {
        "cht": "評分模板",
        "en": "Score Template",
        "jp": "スコアテンプレート",
        "kr": "채점 템플릿",
    },
    "综合评级": {
        "cht": "綜合評級",
        "en": "Overall Rating",
        "jp": "総合ランク",
        "kr": "종합 등급",
    },
    "声骸培养目标参考": {
        "cht": "聲骸培養目標參考",
        "en": "Echo Optimization Reference",
        "jp": "音骸育成参考目標",
        "kr": "음해 육성 참고 목표",
    },
    "模板声骸": {
        "cht": "模板聲骸",
        "en": "Template",
        "jp": "テンプレ",
        "kr": "템플릿",
    },
    # 评分备注 (partial 匹配, 数字保留原样; "共鸣效率"/"暴击" 已在 stats 注册)
    "暴击率": {
        "cht": "暴擊率",
        "en": "Crit. Rate",
        "jp": "クリ率",
        "kr": "크리티컬 확률",
    },
    "暴击率已接近或超过上限": {
        "cht": "暴擊率已接近或超過上限",
        "en": "Crit. Rate is near or above the cap",
        "jp": "クリ率が上限付近または超過",
        "kr": "크리티컬 확률이 상한에 근접 또는 초과",
    },
    "未达推荐值": {
        "cht": "未達推薦值",
        "en": "is below recommended",
        "jp": "は推奨値に未達",
        "kr": "권장값 미달",
    },
    "超出": {
        "cht": "超出",
        "en": "exceeds",
        "jp": "超過",
        "kr": "초과",
    },
    "多余": {
        "cht": "多餘",
        "en": "extra",
        "jp": "余分な",
        "kr": "초과",
    },
    "无收益": {
        "cht": "無收益",
        "en": "no gain",
        "jp": "無効",
        "kr": "효과 없음",
    },
    "建议提升词条方向": {
        "cht": "建議提升詞條方向",
        "en": "Suggested Stat",
        "jp": "おすすめステータス",
        "kr": "추천 옵션",
    },
    "词条提升收益情况": {
        "cht": "詞條提升收益情況",
        "en": "Stat Gain",
        "jp": "ステータス収益",
        "kr": "옵션 수익",
    },
    "备注": {
        "cht": "備註",
        "en": "Notes",
        "jp": "備考",
        "kr": "비고",
    },
    "综合评分规则": {
        "cht": "綜合評分規則",
        "en": "Scoring Rules",
        "jp": "総合スコアのルール",
        "kr": "종합 점수 규칙",
    },
    "评分细则请发送": {
        "cht": "評分細則請發送",
        "en": "For details send",
        "jp": "詳細は次を送信",
        "kr": "세부 규칙은 다음을 전송",
    },
    "测试中": {
        "cht": "測試中",
        "en": "Testing",
        "jp": "テスト中",
        "kr": "테스트 중",
    },
    "以2-3分钟的常规队伍循环为基础，根据当前套装和装备求解得到最优期望伤害的词条作为基准计分": {
        "cht": "以2-3分鐘的常規隊伍循環為基礎，根據當前套裝和裝備求解得到最優期望傷害的詞條作為基準計分",
        "en": "Based on a standard 2-3 min team rotation, the substats giving the best expected damage for your current set and weapon are solved as the full-score baseline.",
        "jp": "2-3分の通常パーティローテーションを基準に、現在のセット・武器で期待ダメージが最大となるステータスを求めて満点基準とします。",
        "kr": "2-3분 일반 팀 로테이션을 기준으로 현재 세트·무기에서 기대 피해가 가장 높은 옵션을 구해 만점 기준으로 삼습니다.",
    },
    "由于共鸣效率会影响限定时间内循环次数，作为分段的独立乘区。单通等特殊场景不适用综合评分": {
        "cht": "由於共鳴效率會影響限定時間內循環次數，作為分段的獨立乘區。單通等特殊場景不適用綜合評分",
        "en": "Energy Regen affects rotation count within the time limit, so it is treated as a piecewise independent multiplier. The score does not apply to special cases like single-target burst clears.",
        "jp": "共鳴効率は制限時間内のローテーション回数に影響するため、区分ごとの独立乗算区として扱います。単発撃破などの特殊シーンには総合スコアは適用されません。",
        "kr": "공명 효율은 제한 시간 내 로테이션 횟수에 영향을 주므로 구간별 독립 곱연산 구역으로 처리합니다. 원턴 격파 등 특수 상황에는 종합 점수가 적용되지 않습니다.",
    },
    "显示的共鸣效率部分建议仅对于循环流畅度考虑，共效挂钩的加成等会另外计算收益得分": {
        "cht": "顯示的共鳴效率部分建議僅對於循環流暢度考慮，共效掛鉤的加成等會另外計算收益得分",
        "en": "The Energy Regen suggestion shown only concerns rotation fluency; bonuses tied to Energy Regen are scored separately.",
        "jp": "表示される共鳴効率の提案はローテーションの円滑さのみを考慮したもので、共鳴効率に連動する補正などは別途収益として計算されます。",
        "kr": "표시되는 공명 효율 관련 제안은 로테이션 원활도만 고려한 것이며, 공명 효율과 연동된 보너스 등은 별도로 수익 점수로 계산됩니다.",
    },
    "最优面板共效可能由于词条取最大值导致偏高，请折算为常见效率词条数值": {
        "cht": "最優面板共效可能由於詞條取最大值導致偏高，請折算為常見效率詞條數值",
        "en": "The optimal panel's Energy Regen may look high since substats use max rolls; convert it to typical Energy Regen substat counts.",
        "jp": "最適パネルの共鳴効率はサブステータスを最大値で計算するため高めに表示されます。一般的な効率ステータス数に換算してください。",
        "kr": "최적 패널의 공명 효율은 부옵션을 최댓값으로 계산하여 높게 표시될 수 있습니다. 일반적인 효율 옵션 수치로 환산해 주세요.",
    },
    "部分角色4c可能显示为攻击，该计算基于副词条双爆满值，请根据实际情况进行搭配": {
        "cht": "部分角色4c可能顯示為攻擊，該計算基於副詞條雙爆滿值，請根據實際情況進行搭配",
        "en": "On some characters the 4-cost main stat may show as ATK; this assumes substats at max double-crit (Crit Rate + Crit DMG) rolls, so pair according to your actual situation.",
        "jp": "一部のキャラクターでは4コストのメインが攻撃と表示される場合があります。これはサブステータスを会心率・会心ダメージ最大値で計算した結果のため、実際の状況に合わせて編成してください。",
        "kr": "일부 캐릭터는 4코스트 메인 옵션이 공격으로 표시될 수 있습니다. 이는 부옵션을 치확·치피 최댓값으로 계산한 결과이니 실제 상황에 맞게 조합하세요.",
    },
    "仅针对常见队伍和流程，请以实际情况为准。如有建议请联系开发者提供反馈": {
        "cht": "僅針對常見隊伍和流程，請以實際情況為準。如有建議請聯繫開發者提供反饋",
        "en": "Based on common teams and rotations only; please refer to your actual situation. For suggestions, contact the developer with feedback.",
        "jp": "一般的なパーティとローテーションのみを対象としています。実際の状況を優先してください。ご提案は開発者までフィードバックをお願いします。",
        "kr": "일반적인 팀과 로테이션만을 대상으로 합니다. 실제 상황을 기준으로 하세요. 건의 사항은 개발자에게 피드백해 주세요.",
    },
    # 伤害区
    "伤害类型": {
        "cht": "傷害類型",
        "en": "DMG Type",
        "jp": "ダメージ種別",
        "kr": "피해 유형",
    },
    "暴击伤害": {
        "cht": "暴擊傷害",
        "en": "Crit. DMG",
        "jp": "クリティカルダメージ",
        "kr": "크리티컬 피해",
    },
    "期望伤害": {
        "cht": "期望傷害",
        "en": "Expected DMG",
        "jp": "期待ダメージ",
        "kr": "기대 피해",
    },
    "buff列表": {
        "cht": "buff列表",
        "en": "Buff List",
        "jp": "バフ一覧",
        "kr": "버프 목록",
    },
    # 排名
    "评分排名": {
        "cht": "評分排名",
        "en": "Score Rank",
        "jp": "スコア順位",
        "kr": "점수 순위",
    },
    "估计评分排名": {
        "cht": "估計評分排名",
        "en": "Est. Score Rank",
        "jp": "推定スコア順位",
        "kr": "예상 점수 순위",
    },
    "伤害排名": {
        "cht": "傷害排名",
        "en": "DMG Rank",
        "jp": "ダメージ順位",
        "kr": "피해 순위",
    },
    "估计伤害排名": {
        "cht": "估計傷害排名",
        "en": "Est. DMG Rank",
        "jp": "推定ダメージ順位",
        "kr": "예상 피해 순위",
    },
})
