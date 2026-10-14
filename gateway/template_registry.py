"""
Unified PPT Skill & Template Registry for Personal Agent ProMedia Studio.
Integrates:
1. GordenSun/GordenPPTSkill (https://github.com/GordenSun/GordenPPTSkill) — All 21 real Chinese PPTX templates + non-destructive slot builder
2. zarazhangrui/frontend-slides (https://github.com/zarazhangrui/frontend-slides) — Curated Editorial Web Slides
3. hugohe3/ppt-master (https://github.com/hugohe3/ppt-master) — Native SVG & Brand Presentation Master
4. User's Local Custom Templates (`yonyou-ci-bg`, `abu9-exec-report`, `guizang-swiss-html`, `obsidian-roadshow`)
"""
import json
import pathlib
from typing import Dict, Any, List

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
GORDEN_ROOT = BASE_DIR / "worker" / "external_ppt_skills" / "GordenPPTSkill"
FRONTEND_SLIDES_ROOT = BASE_DIR / "worker" / "external_ppt_skills" / "frontend-slides"
PPT_MASTER_ROOT = BASE_DIR / "worker" / "external_ppt_skills" / "ppt-master"

YONYOU_REAL_PPTX_PATH = pathlib.Path(
    "/Users/flyignick/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/"
    "flyingnick_7d31/msg/file/2026-05/2-2026用友高端BG PPT素材库模板.pptx"
)

# Curated semantic keywords & descriptions for GordenPPTSkill's 21 templates
GORDEN_META: Dict[str, Dict[str, Any]] = {
    "mckinsey-style": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 战略咨询",
        "desc": "麦肯锡专业咨询风（37页），酱红配深蓝灰，含金字塔、漏斗、矩阵对比、总分结构，适合战略规划与高管提案。",
        "keywords": ["麦肯锡", "咨询", "战略", "mckinsey", "商业分析", "提案", "金字塔", "行业研究"],
        "featured": True,
    },
    "minimal-business-summary": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 极简商务",
        "desc": "简约商务总结汇报（16页），深蓝白高留白版式，季度/年度工作汇报首选。",
        "keywords": ["简约", "商务总结", "年度汇报", "工作总结", "minimal", "述职"],
        "featured": True,
    },
    "premium-corp": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 大厂高级感",
        "desc": "高级感大厂 PPT 合辑（35页），涵盖大厂战略、运营、数据看板与思维模型。",
        "keywords": ["大厂", "高级感", "互联网", "字节", "阿里", "腾讯", "晋升", "premium"],
        "featured": True,
    },
    "architecture-deck": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 系统架构图",
        "desc": "领导最爱的架构图合辑（37页），内置大厂真实 AI 架构、技术底座、供应链与业务中台拓扑图。",
        "keywords": ["架构", "架构图", "系统设计", "中台", "技术方案", "拓扑", "AI架构", "供应链"],
        "featured": True,
    },
    "data-viz-deck": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 原生数据图表",
        "desc": "重型数据可视化合辑（41页），含 20+ 原生可编辑图表页，适合财务、BI 与数据复盘。",
        "keywords": ["数据可视化", "图表", "BI", "数据分析", "指标", "统计", "财报"],
        "featured": True,
    },
    "operations-deck": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 运营增长",
        "desc": "互联网运营全场景合辑（52页），覆盖私域转化、生命周期、AARRR 漏斗与活动复盘。",
        "keywords": ["运营", "私域", "增长", "转化", "用户", "活动复盘", "产品运营"],
        "featured": False,
    },
    "report-savior": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 汇报全能库",
        "desc": "商业汇报救命合辑（44页），涵盖 SWOT、PEST、鱼骨图、树状图与屋型架构。",
        "keywords": ["救命", "全能", "SWOT", "PEST", "鱼骨图", "商业汇报"],
        "featured": False,
    },
    "competition-speech": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 竞聘述职",
        "desc": "岗位竞聘与晋升述职合辑（59页），内置 KISS/PDCA/SWOT 个人能力与项目复盘模型。",
        "keywords": ["竞聘", "晋升", "答辩", "个人述职", "岗位", "PDCA"],
        "featured": False,
    },
    "report-massive-models": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 思维模型库",
        "desc": "汇报合辑·思维模型与复盘（38页），专注方法论、逻辑推演与项目复盘。",
        "keywords": ["思维模型", "复盘", "方法论", "模型库"],
        "featured": False,
    },
    "report-massive-charts": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 业绩图表库",
        "desc": "汇报合辑·数据图表与业绩（38页），专注销售漏斗、财务达成与业绩对比。",
        "keywords": ["业绩", "销售", "漏斗", "达成率"],
        "featured": False,
    },
    "report-massive-reports": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 综合工作汇报",
        "desc": "汇报合辑·工作汇报与竞聘（37页），标准总分结构与金字塔汇报。",
        "keywords": ["部门汇报", "周报", "月报"],
        "featured": False,
    },
    "quarterly-illust": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 酸性插画Y2K",
        "desc": "蓝灰酸性插画季度总结（19页），亮蓝配黑白插画，年轻化互联网创意风。",
        "keywords": ["插画", "酸性", "Y2K", "创意", "年轻"],
        "featured": False,
    },
    "geometric-summary": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 多彩几何",
        "desc": "简约几何工作总结（21页），蓝红黄绿四色几何切片，视觉明快。",
        "keywords": ["几何", "多彩", "活力"],
        "featured": False,
    },
    "thesis-formula": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 学术开题",
        "desc": "开题报告万能公式（39页），暖米配深蓝，背景/意义/现状/方法四段标准学术结构。",
        "keywords": ["开题", "论文", "学术", "答辩", "研究方法", "课题", "高校"],
        "featured": True,
    },
    "top-thesis": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 名校酒红学术",
        "desc": "名校开题报告合辑（39页），典雅学术酒红配色，硕博答辩与课题申报首选。",
        "keywords": ["名校", "硕博", "毕业答辩", "酒红", "课题申报"],
        "featured": False,
    },
    "thesis-novice": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 墨绿学术方法",
        "desc": "多专业开题方法论库（32页），学院派墨绿配色。",
        "keywords": ["方法论", "跨专业", "墨绿"],
        "featured": False,
    },
    "red-patriot-youth": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 党建思政",
        "desc": "新时代青年红色教育（16页），庄重党政红配金。",
        "keywords": ["党建", "党政", "红色", "思政", "青年"],
        "featured": False,
    },
    "red-patriot-general": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 主题党日",
        "desc": "红色爱国主题教育通用（25页），金色书法与红绸设计。",
        "keywords": ["党课", "主题教育", "爱国"],
        "featured": False,
    },
    "red-teaching-framework": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 教学大赛框架",
        "desc": "高级红色教学实施框架（30页），高密度教学逻辑图解，教学比赛与说课首选。",
        "keywords": ["教学比赛", "说课", "教案", "课程建设", "教学框架"],
        "featured": False,
    },
    "red-teaching-models": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 数智教学图解",
        "desc": "高级红色数智教学图解（30页），含漏斗、齿轮、鱼骨与放射教学模型。",
        "keywords": ["数智教学", "课改", "教学图解"],
        "featured": False,
    },
    "cute-orange-class": {
        "category": "gorden-ppt-skill",
        "badge": "GordenPPTSkill · 暖橙卡通课件",
        "desc": "橙色可爱卡通教学（17页），手绘风适合培训与公开课。",
        "keywords": ["卡通", "公开课", "培训课件", "K12"],
        "featured": False,
    },
}


def _build_template_library() -> Dict[str, Dict[str, Any]]:
    lib: Dict[str, Dict[str, Any]] = {
        "yonyou-ci-bg": {
            "id": "yonyou-ci-bg",
            "name": "用友高端 BG 商务蓝白母版",
            "skill_engine": "client-ci-ppt",
            "badge": "本机专属 Skill · 政企B2B",
            "source_skill": "~/.codex/skills/client-ci-ppt-image-deck",
            "real_pptx_exists": YONYOU_REAL_PPTX_PATH.exists(),
            "real_pptx_path": str(YONYOU_REAL_PPTX_PATH),
            "preview_url": None,
            "featured": True,
            "description": "源自您本机『2026用友高端BG PPT素材库模板』，科技蓝配高净值浅灰白底色，适合政企数字化方案。",
            "keywords": ["用友", "高端BG", "政企", "B2B", "数字化", "ERP", "BIP", "客户方案", "蓝白", "采购"],
            "palette": {
                "name": "Yonyou Enterprise Blue (用友高端BG蓝白)",
                "is_light": True,
                "bg": "#F4F7FB",
                "surface": "#FFFFFF",
                "border": "#D6E0F0",
                "primary": "#0052D9",
                "accent": "#E60012",
                "emerald": "#059669",
                "text": "#0F172A",
                "muted": "#475569",
                "brand_tag": "YONYOU BIP · ENTERPRISE EXECUTIVE DECK",
            },
        },
        "abu9-exec-report": {
            "id": "abu9-exec-report",
            "name": "ABU9 友车科技经营汇报母版",
            "skill_engine": "artifact-template-abu9",
            "badge": "本机专属 Skill · 经营述职",
            "source_skill": "~/.codex/skills/artifact-template-abu9",
            "real_pptx_exists": True,
            "real_pptx_path": "/Users/flyignick/.codex/skills/artifact-template-abu9/SKILL.md",
            "preview_url": None,
            "featured": True,
            "description": "源自您本机『artifact-template-abu9』公司经营汇报规范，纯白底色配用友红 (#E60012) 顶部色带。",
            "keywords": ["ABU9", "友车", "经营", "财务", "季度", "月度", "红标", "白底", "预算", "毛利"],
            "palette": {
                "name": "ABU9 Executive White & Red (经营汇报白底红标)",
                "is_light": True,
                "bg": "#FFFFFF",
                "surface": "#F8FAFC",
                "border": "#E2E8F0",
                "primary": "#E60012",
                "accent": "#1E293B",
                "emerald": "#0D9488",
                "text": "#1E293B",
                "muted": "#64748B",
                "brand_tag": "ABU9 EXECUTIVE REPORT · 经营管理汇报",
            },
        },
        "guizang-swiss-html": {
            "id": "guizang-swiss-html",
            "name": "归藏 Swiss × Frontend-Slides 交互网页母版",
            "skill_engine": "frontend-slides",
            "badge": "GitHub frontend-slides + 归藏",
            "source_skill": "github.com/zarazhangrui/frontend-slides + ~/.codex/skills/guizang-ppt-skill",
            "real_pptx_exists": True,
            "real_pptx_path": str(FRONTEND_SLIDES_ROOT / "SKILL.md"),
            "preview_url": None,
            "featured": True,
            "description": "融合归藏瑞士网格与 GitHub 知名 frontend-slides 交互式网页演示技能，支持键盘翻页、全屏路演与 PPTX 双输出。",
            "keywords": ["归藏", "瑞士", "杂志", "极简", "frontend-slides", "网页PPT", "HTML", "交互"],
            "palette": {
                "name": "Swiss Editorial Warm Paper (瑞士国际主义杂志风)",
                "is_light": True,
                "bg": "#F7F6F2",
                "surface": "#FFFFFF",
                "border": "#D4D2C8",
                "primary": "#D9381E",
                "accent": "#111111",
                "emerald": "#15803D",
                "text": "#111111",
                "muted": "#57534E",
                "brand_tag": "SWISS INTERNATIONAL GRID · FRONTEND SLIDES",
            },
        },
        "ppt-master-svg": {
            "id": "ppt-master-svg",
            "name": "PPT-Master 原生矢量图表路演母版",
            "skill_engine": "ppt-master",
            "badge": "GitHub hugohe3/ppt-master",
            "source_skill": "github.com/hugohe3/ppt-master",
            "real_pptx_exists": PPT_MASTER_ROOT.exists(),
            "real_pptx_path": str(PPT_MASTER_ROOT / "skills" / "ppt-master" / "SKILL.md"),
            "preview_url": None,
            "featured": True,
            "description": "集成 GitHub 知名 hugohe3/ppt-master 技能体系，高对比度商务科技版式，内嵌 300 DPI 数据可视化。",
            "keywords": ["ppt-master", "路演", "融资", "BP", "发布会", "科技", "深色", "黑曜石", "Agent"],
            "palette": {
                "name": "PPT-Master Executive Dark",
                "is_light": False,
                "bg": "#0B0F19",
                "surface": "#161F33",
                "border": "#28354F",
                "primary": "#38BDF8",
                "accent": "#6366F1",
                "emerald": "#10B981",
                "text": "#F8FAFC",
                "muted": "#94A3B8",
                "brand_tag": "PPT-MASTER · EXECUTIVE ROADSHOW DECK",
            },
        },
        "obsidian-roadshow": {
            "id": "obsidian-roadshow",
            "name": "Obsidian 深邃黑曜石科技路演母版",
            "skill_engine": "pptx-pro",
            "badge": "内置高定 · 创投路演",
            "source_skill": "worker/agent_skills/.claude/skills/pptx-pro",
            "real_pptx_exists": True,
            "real_pptx_path": "builtin://obsidian-roadshow",
            "preview_url": None,
            "featured": False,
            "description": "深邃黑曜石搭配电光蓝，适合 AI 产品发布与技术宣讲。",
            "keywords": ["黑曜石", "暗黑", "技术宣讲"],
            "palette": {
                "name": "Obsidian Indigo (深邃黑曜石)",
                "is_light": False,
                "bg": "#0B0F19",
                "surface": "#161F33",
                "border": "#28354F",
                "primary": "#38BDF8",
                "accent": "#6366F1",
                "emerald": "#10B981",
                "text": "#F8FAFC",
                "muted": "#94A3B8",
                "brand_tag": "PERSONAL AGENT · EXECUTIVE ROADSHOW DECK",
            },
        },
    }

    # Dynamically load all 21 real templates from GordenSun/GordenPPTSkill
    tpl_root = GORDEN_ROOT / "templates"
    if tpl_root.exists():
        for slug_dir in sorted(tpl_root.iterdir()):
            if not slug_dir.is_dir():
                continue
            detail_p = slug_dir / "detail.json"
            pptx_p = slug_dir / "template.pptx"
            if not detail_p.exists() or not pptx_p.exists():
                continue
            try:
                d = json.loads(detail_p.read_text(encoding="utf-8"))
                slug = slug_dir.name
                meta = GORDEN_META.get(slug, {})
                colors = d.get("theme_colors", ["#1F3A93", "#3F6FCC"])
                primary_c = colors[0] if colors else "#1F3A93"
                accent_c = colors[1] if len(colors) > 1 else "#B73E3E"
                tpl_id = f"gorden:{slug}"
                lib[tpl_id] = {
                    "id": tpl_id,
                    "gorden_slug": slug,
                    "name": f"{d.get('name', slug)} (GordenPPTSkill)",
                    "skill_engine": "gorden-ppt-skill",
                    "badge": meta.get("badge", f"GordenPPTSkill · {d.get('slide_count', 20)}页母版"),
                    "source_skill": f"github.com/GordenSun/GordenPPTSkill/templates/{slug}",
                    "real_pptx_exists": True,
                    "real_pptx_path": str(pptx_p),
                    "detail_json_path": str(detail_p),
                    "preview_url": f"/api/gorden-preview/{slug}",
                    "template_total_slides": d.get("slide_count", 20),
                    "featured": bool(meta.get("featured", False)),
                    "description": meta.get("desc", f"GordenPPTSkill 精修中文母版《{d.get('name')}》，共 {d.get('slide_count')} 页原始复杂排版，支持非破坏性槽位替换。"),
                    "keywords": meta.get("keywords", [d.get("name", ""), slug]),
                    "palette": {
                        "name": f"GordenPPTSkill · {d.get('name', slug)}",
                        "is_light": True,
                        "bg": "#F8FAFC",
                        "surface": "#FFFFFF",
                        "border": "#E2E8F0",
                        "primary": primary_c,
                        "accent": accent_c,
                        "emerald": "#059669",
                        "text": "#0F172A",
                        "muted": "#475569",
                        "brand_tag": f"GORDEN PPT SKILL · {slug.upper()}",
                    },
                }
            except Exception:
                continue

    return lib


TEMPLATE_LIBRARY: Dict[str, Dict[str, Any]] = _build_template_library()


def list_available_templates() -> List[Dict[str, Any]]:
    return list(TEMPLATE_LIBRARY.values())


def list_installed_ppt_skills() -> List[Dict[str, Any]]:
    """Return metadata of all integrated GitHub & local PPT skills."""
    return [
        {
            "id": "gorden-ppt-skill",
            "name": "GordenSun/GordenPPTSkill",
            "github": "https://github.com/GordenSun/GordenPPTSkill",
            "stars": "3.6k+",
            "templates_count": 21,
            "mode": "非破坏性真实 .pptx 槽位替换 (build_pptx.py + 21套精修中文模板)",
            "installed": (GORDEN_ROOT / "SKILL.md").exists(),
        },
        {
            "id": "frontend-slides",
            "name": "zarazhangrui/frontend-slides",
            "github": "https://github.com/zarazhangrui/frontend-slides",
            "stars": "2.8k+",
            "templates_count": 12,
            "mode": "高审美零 AI 味交互式 HTML/CSS 网页演示文稿与键盘全屏控制",
            "installed": (FRONTEND_SLIDES_ROOT / "SKILL.md").exists(),
        },
        {
            "id": "ppt-master",
            "name": "hugohe3/ppt-master",
            "github": "https://github.com/hugohe3/ppt-master",
            "stars": "1.9k+",
            "templates_count": 8,
            "mode": "SVG 原生形状与高密度商业图表生成管线",
            "installed": (PPT_MASTER_ROOT / "skills" / "ppt-master" / "SKILL.md").exists(),
        },
        {
            "id": "local-enterprise-skills",
            "name": "本机企业专属母版库 (用友高端BG / 友车ABU9 / 归藏Swiss)",
            "github": "local://~/.codex/skills",
            "stars": "Private",
            "templates_count": 4,
            "mode": "针对用友政企方案、ABU9 经营述职与瑞士网格定制",
            "installed": True,
        },
    ]


def match_template_for_prompt(prompt_cn: str, requested_template_id: str = "auto") -> Dict[str, Any]:
    """
    Match the most suitable presentation template across GordenPPTSkill (21 templates),
    frontend-slides, ppt-master, and local enterprise templates.
    """
    # Allow shorthand gorden slug lookup
    if requested_template_id and requested_template_id != "auto":
        if requested_template_id in TEMPLATE_LIBRARY:
            tpl = TEMPLATE_LIBRARY[requested_template_id]
            return {
                "template": tpl,
                "match_mode": "manual",
                "match_reason_cn": f"已按您的选择锁定母版：《{tpl['name']}》（引擎：{tpl['skill_engine']}）",
            }
        if f"gorden:{requested_template_id}" in TEMPLATE_LIBRARY:
            tpl = TEMPLATE_LIBRARY[f"gorden:{requested_template_id}"]
            return {
                "template": tpl,
                "match_mode": "manual",
                "match_reason_cn": f"已按您的选择锁定 GordenPPTSkill 母版：《{tpl['name']}》",
            }

    best_id = "gorden:mckinsey-style"
    best_score = 0
    matched_words: List[str] = []

    for tpl_id, tpl in TEMPLATE_LIBRARY.items():
        hits = [kw for kw in tpl.get("keywords", []) if kw and kw.lower() in prompt_cn.lower()]
        if len(hits) > best_score:
            best_score = len(hits)
            best_id = tpl_id
            matched_words = hits

    if best_score == 0:
        if any(w in prompt_cn for w in ["用友", "政企", "BIP", "ERP", "采购"]):
            best_id = "yonyou-ci-bg"
            matched_words = ["用友政企场景"]
        elif any(w in prompt_cn for w in ["ABU9", "友车", "经营", "红标"]):
            best_id = "abu9-exec-report"
            matched_words = ["ABU9经营汇报"]
        elif any(w in prompt_cn for w in ["架构", "系统", "技术", "底座", "拓扑"]):
            best_id = "gorden:architecture-deck"
            matched_words = ["系统架构场景 → GordenPPTSkill"]
        elif any(w in prompt_cn for w in ["总结", "季度", "年度", "周报", "复盘"]):
            best_id = "gorden:minimal-business-summary"
            matched_words = ["商务总结场景 → GordenPPTSkill"]
        else:
            best_id = "gorden:mckinsey-style"
            matched_words = ["战略咨询场景 → GordenPPTSkill 麦肯锡母版"]

    tpl = TEMPLATE_LIBRARY.get(best_id) or next(iter(TEMPLATE_LIBRARY.values()))
    reason = f"智能识别到「{' / '.join(matched_words[:3])}」，已匹配《{tpl['name']}》（引擎：{tpl['skill_engine']}）"
    return {
        "template": tpl,
        "match_mode": "auto_matched",
        "match_reason_cn": reason,
    }
