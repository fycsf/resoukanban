import os
import requests
import calendar
import re
import json
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timedelta
from zhdate import ZhDate

# =====================================================================
# 🌟 第一部分：设备配置区（每台设备独立设置） 🌟
# =====================================================================

DEVICES = [
    {
        "mac_env": "ZECTRIX_MAC_1",
        "name": "办公室屏",
        "pages": "1,2,3,4",
        "city_adcode": "330102",
        "wttr_location": "Shangcheng,Hangzhou",
        "city_display": "上城区 | 市民中心打工地",
        "hotlist_source": "baidu",
    },
    {
        "mac_env": "ZECTRIX_MAC_2",
        "name": "家庭屏",
        "pages": "1,2,3,4",
        "city_adcode": "330106",
        "wttr_location": "Xihu,Hangzhou",
        "city_display": "西湖区 | 文萃苑的家",
        "hotlist_source": "baidu",
    },
]

# =====================================================================
# 🔒 第二部分：核心密钥区 🔒
# =====================================================================
API_KEY = os.environ.get("ZECTRIX_API_KEY")
AMAP_KEY = os.environ.get("AMAP_WEATHER_KEY")

# =====================================================================
# ⚙️ 第三部分：底层运行逻辑 ⚙️
# =====================================================================

FONT_PATH = "font.ttf"
try:
    font_huge = ImageFont.truetype(FONT_PATH, 65)
    font_title = ImageFont.truetype(FONT_PATH, 24)
    font_item = ImageFont.truetype(FONT_PATH, 18)
    font_small = ImageFont.truetype(FONT_PATH, 14)
    font_tiny = ImageFont.truetype(FONT_PATH, 11)
    font_48 = ImageFont.truetype(FONT_PATH, 48)
    font_36 = ImageFont.truetype(FONT_PATH, 36)
except:
    print("❌ 错误: 找不到 font.ttf")
    exit(1)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

# --- 工具函数 ---
def get_clothing_advice(temp):
    try:
        t = int(temp)
        if t >= 28: return "建议穿短袖、短裤，注意防晒补水。"
        elif t >= 22: return "体感舒适，建议穿 T 恤配薄长裤。"
        elif t >= 16: return "建议穿长袖衬衫、卫衣或单层薄外套。"
        elif t >= 10: return "气温微凉，建议穿夹克、风衣或毛衣。"
        elif t >= 5: return "建议穿大衣、厚毛衣或薄款羽绒服。"
        else: return "天气寒冷，建议穿厚羽绒服，注意防寒。"
    except:
        return "请根据实际体感气温调整着装。"

def push_image(img, page_id, mac, device_name):
    img.save(f"page_{page_id}_{mac[-4:]}.png")
    api_headers = {"X-API-Key": API_KEY}
    files = {"images": (f"page_{page_id}.png", open(f"page_{page_id}_{mac[-4:]}.png", "rb"), "image/png")}
    data = {"dither": "true", "pageId": str(page_id)}
    push_url = f"https://cloud.zectrix.com/open/v1/devices/{mac}/display/image"
    try:
        res = requests.post(push_url, headers=api_headers, files=files, data=data, timeout=30)
        if res.status_code == 200:
            print(f"   ✅ Page {page_id} 推送成功")
            return True
        else:
            print(f"   ❌ Page {page_id} 推送失败: HTTP {res.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Page {page_id} 推送异常: {e}")
        return False

# --- 智能摘要：按完整句子提取，保证简介不断词 ---
def smart_summary(text, max_chars=60):
    """提取1-2个完整句子作为简介，保证语义完整、不断词"""
    if not text:
        return ""
    # 清理HTML和多余空格
    text = re.sub(r'<[^>]+>', '', text).strip()
    text = re.sub(r'\s+', ' ', text)
    
    if len(text) <= max_chars:
        return text
    
    # 按中文标点分割成句子
    sentences = re.split(r'([。！？；.!?])', text)
    full_sentences = []
    i = 0
    while i < len(sentences):
        s = sentences[i].strip()
        if i + 1 < len(sentences) and sentences[i+1] in '。！？；.!?':
            s += sentences[i+1]
            i += 2
        else:
            i += 1
        if s:
            full_sentences.append(s)
    
    # 取前1-2个句子，总长度不超过max_chars
    result = ""
    for s in full_sentences[:2]:
        if len(result) + len(s) <= max_chars:
            result += s
        else:
            # 如果第一个句子就超长，在max_chars内找最后一个标点截断
            if not result:
                truncated = text[:max_chars]
                # 从末尾往前找标点
                for punct in '，、；：,;':
                    pos = truncated.rfind(punct)
                    if pos > max_chars * 0.5:  # 至少保留一半
                        return truncated[:pos+1]
                # 找不到标点就截断加省略号
                return truncated[:-1] + "…"
            break
    
    return result if result else text[:max_chars-1] + "…"

# --- 按像素宽度自动换行 ---
def wrap_text_by_width(draw, text, font, max_width):
    """按像素宽度自动换行，返回多行文本列表"""
    if not text:
        return []
    lines = []
    current_line = ""
    for char in text:
        test_line = current_line + char
        try:
            w = draw.textlength(test_line, font=font)
        except AttributeError:
            w = draw.textbbox((0, 0), test_line, font=font)[2]
        if w <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = char
    if current_line:
        lines.append(current_line)
    return lines

# --- 节气与农历 ---
def get_solar_term(year, month, day):
    term_table = {
        (2024,2,4):"立春", (2024,2,19):"雨水", (2024,3,5):"惊蛰", (2024,3,20):"春分",
        (2024,4,4):"清明", (2024,4,19):"谷雨", (2024,5,5):"立夏", (2024,5,20):"小满",
        (2024,6,5):"芒种", (2024,6,21):"夏至", (2024,7,6):"小暑", (2024,7,22):"大暑",
        (2024,8,7):"立秋", (2024,8,22):"处暑", (2024,9,7):"白露", (2024,9,22):"秋分",
        (2024,10,8):"寒露", (2024,10,23):"霜降", (2024,11,7):"立冬", (2024,11,22):"小雪",
        (2024,12,6):"大雪", (2024,12,21):"冬至",
        (2025,1,5):"小寒", (2025,1,20):"大寒", (2025,2,3):"立春", (2025,2,18):"雨水",
        (2025,3,5):"惊蛰", (2025,3,20):"春分", (2025,4,4):"清明", (2025,4,20):"谷雨",
        (2025,5,5):"立夏", (2025,5,21):"小满", (2025,6,5):"芒种", (2025,6,21):"夏至",
        (2025,7,7):"小暑", (2025,7,22):"大暑", (2025,8,7):"立秋", (2025,8,23):"处暑",
        (2025,9,7):"白露", (2025,9,22):"秋分", (2025,10,8):"寒露", (2025,10,23):"霜降",
        (2025,11,7):"立冬", (2025,11,22):"小雪", (2025,12,7):"大雪", (2025,12,21):"冬至",
        (2026,1,5):"小寒", (2026,1,20):"大寒", (2026,2,4):"立春", (2026,2,18):"雨水",
        (2026,3,5):"惊蛰", (2026,3,20):"春分", (2026,4,5):"清明", (2026,4,20):"谷雨",
        (2026,5,5):"立夏", (2026,5,21):"小满", (2026,6,6):"芒种", (2026,6,21):"夏至",
        (2026,7,7):"小暑", (2026,7,23):"大暑", (2026,8,7):"立秋", (2026,8,23):"处暑",
        (2026,9,7):"白露", (2026,9,23):"秋分", (2026,10,8):"寒露", (2026,10,23):"霜降",
        (2026,11,7):"立冬", (2026,11,22):"小雪", (2026,12,7):"大雪", (2026,12,21):"冬至",
        (2027,1,5):"小寒", (2027,1,20):"大寒", (2027,2,4):"立春", (2027,2,19):"雨水",
        (2027,3,6):"惊蛰", (2027,3,21):"春分", (2027,4,5):"清明", (2027,4,20):"谷雨",
    }
    return term_table.get((year, month, day), None)

def get_lunar_or_festival(y, m, d):
    term = get_solar_term(y, m, d)
    if term: return term
    solar_fests = {
        (1,1):"元旦", (2,14):"情人节", (3,8):"妇女节", (4,1):"愚人节",
        (5,1):"劳动节", (6,1):"儿童节", (7,1):"建党节", (8,1):"建军节",
        (9,10):"教师节", (10,1):"国庆节", (12,25):"圣诞节"
    }
    if (m, d) in solar_fests: return solar_fests[(m, d)]
    try:
        lunar = ZhDate.from_datetime(datetime(y, m, d))
        lm, ld = lunar.lunar_month, lunar.lunar_day
        lunar_fests = {
            (1,1):"春节", (1,15):"元宵节", (5,5):"端午节",
            (7,7):"七夕节", (8,15):"中秋节", (9,9):"重阳节", (12,30):"除夕"
        }
        if (lm, ld) in lunar_fests: return lunar_fests[(lm, ld)]
        days = ["初一","初二","初三","初四","初五","初六","初七","初八","初九","初十",
                "十一","十二","十三","十四","十五","十六","十七","十八","十九","二十",
                "廿一","廿二","廿三","廿四","廿五","廿六","廿七","廿八","廿九","三十"]
        months = ["正月","二月","三月","四月","五月","六月","七月","八月","九月","十月","冬月","腊月"]
        if ld == 1: return months[lm-1]
        return days[ld-1]
    except:
        return ""

# --- 获取热搜数据 ---
def get_hotlist_data(source):
    items = []
    print(f"   正在从 {source} 获取数据...")

    try:
        if source == "baidu":
            url = "https://top.baidu.com/api/board?platform=wise&tab=realtime&limit=10"
            res = requests.get(url, headers=HEADERS, timeout=10).json()
            if res.get("errno") == 0:
                cards = res.get("data", {}).get("cards", [])
                for card in cards:
                    if card.get("component") == "list":
                        for item in card.get("content", [])[:10]:
                            title = item.get("word", item.get("query", "无标题"))
                            # 获取新闻简介
                            desc = item.get("desc", "")
                            if not desc:
                                content_list = item.get("content", [])
                                if content_list and isinstance(content_list, list):
                                    first = content_list[0]
                                    if isinstance(first, dict):
                                        desc = first.get("text", "")
                                    else:
                                        desc = str(first)
                            # 智能摘要：提取1-2个完整句子
                            excerpt = smart_summary(desc, max_chars=62)
                            items.append({"title": title, "excerpt": excerpt})
                        break
            if not items:
                print("   ⚠️ 百度热榜未获取到数据，尝试fallback到知乎...")
                source = "zhihu"

        if source == "zhihu" or (source == "baidu" and not items):
            url = "https://api.zhihu.com/topstory/hot-list"
            res = requests.get(url, headers=HEADERS, timeout=10).json()
            for item in res.get('data', [])[:10]:
                target = item.get('target', {})
                title = target.get('title', '无标题')
                excerpt = target.get('excerpt', '') or target.get('detail_text', '')
                excerpt = smart_summary(excerpt, max_chars=62)
                items.append({"title": title, "excerpt": excerpt})

        elif source == "bilibili":
            url = "https://api.bilibili.com/x/web-interface/wbi/search/square?limit=20"
            res = requests.get(url, headers=HEADERS, timeout=10).json()
            for item in res.get('data', {}).get('trending', {}).get('list', [])[:10]:
                title = item.get('show_name', '无标题')
                items.append({"title": title, "excerpt": ""})

        elif source == "github":
            date_str = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            url = f"https://api.github.com/search/repositories?q=stars:>500+created:>{date_str}&sort=stars&order=desc"
            res = requests.get(url, headers=HEADERS, timeout=10).json()
            for item in res.get('items', [])[:10]:
                title = item.get('full_name', 'unknown')
                desc = item.get('description', '') or 'No description'
                excerpt = smart_summary(desc, max_chars=62)
                items.append({"title": title, "excerpt": excerpt})

        if not items:
            items = [{"title": "暂无热点数据", "excerpt": "请检查网络或稍后重试"}] * 3

    except Exception as e:
        print(f"   ⚠️ 获取失败: {e}")
        items = [{"title": "数据获取失败", "excerpt": "请检查网络或更换热搜源"}] * 3

    return items

# --- 任务：热搜看板（新版：每页3条，标题2行+简介2行，语义完整） ---
def task_hotlist(mac, enabled_pages, source, device_name):
    if "1" not in enabled_pages and "2" not in enabled_pages:
        return 0, 0

    source_map = {
        "baidu": "百度热点",
        "zhihu": "知乎热榜",
        "bilibili": "B站热搜",
        "github": "GitHub 热门"
    }
    items = get_hotlist_data(source)
    title_display = source_map.get(source, "热门看板")

    def draw_list(draw, page_title, items, start_idx):
        # 顶部标题栏
        draw.rounded_rectangle([(10, 8), (390, 42)], radius=8, fill=0)
        draw.text((20, 12), page_title, font=font_title, fill=255)

        y = 48
        last_idx = start_idx
        item_height = 83  # 3条 × 83 = 249，从y=48到y=297，底部留白3px
        max_text_width = 340  # 400 - 序号区38 - 右边距12

        for i in range(start_idx, len(items)):
            if y + 70 > 298:
                break

            current_num = i + 1
            item = items[i]

            # 左侧序号黑底圆角框（高68px，适配双行标题+简介）
            draw.rounded_rectangle([(10, y), (38, y + 68)], radius=6, fill=0)
            num_x = 17 if current_num < 10 else 10
            draw.text((num_x, y + 24), str(current_num), font=font_small, fill=255)

            # 标题：18号字，最多2行，自动换行
            title_lines = wrap_text_by_width(draw, item.get("title", ""), font_item, max_text_width)
            title_lines = title_lines[:2]  # 最多2行
            title_y
