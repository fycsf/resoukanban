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
            title_y = y + 3
            for line in title_lines:
                draw.text((45, title_y), line, font=font_item, fill=0)
                title_y += 22  # 18号字行高约22px

            # 简介：11号字，最多2行（已用smart_summary保证语义完整）
            excerpt = item.get("excerpt", "")
            if excerpt:
                excerpt_lines = wrap_text_by_width(draw, excerpt, font_tiny, max_text_width)
                excerpt_lines = excerpt_lines[:2]
                excerpt_y = y + 3 + len(title_lines) * 22 + 4  # 标题下方留4px间距
                for line in excerpt_lines:
                    draw.text((45, excerpt_y), line, font=font_tiny, fill=0)
                    excerpt_y += 13  # 11号字行高约13px

            # 条目之间加细线分隔（除最后一条）
            if i < start_idx + 2 and i < len(items) - 1:
                line_y = y + item_height - 4
                draw.line([(45, line_y), (390, line_y)], fill=0, width=1)

            y += item_height
            last_idx = i + 1

        return last_idx

    success_count = 0
    next_s = 0

    if "1" in enabled_pages:
        print(f"   生成 Page 1: 热点 (上 1-3)...")
        img1 = Image.new('1', (400, 300), color=255)
        next_s = draw_list(ImageDraw.Draw(img1), f"◆ {title_display} (一)", items, 0)
        if push_image(img1, 1, mac, device_name):
            success_count += 1

    if "2" in enabled_pages:
        print(f"   生成 Page 2: 热点 (下 4-6)...")
        img2 = Image.new('1', (400, 300), color=255)
        start_index = next_s if "1" in enabled_pages else 3
        draw_list(ImageDraw.Draw(img2), f"◆ {title_display} (二)", items, start_index)
        if push_image(img2, 2, mac, device_name):
            success_count += 1

    total_pages = len([p for p in enabled_pages if p in ("1", "2")])
    return success_count, total_pages

# --- 任务：日历 ---
def task_calendar(mac, enabled_pages, device_name):
    if "3" not in enabled_pages:
        return 0, 0

    print(f"   生成 Page 3: 日历...")
    img = Image.new('1', (400, 300), color=255)
    draw = ImageDraw.Draw(img)
    now_utc = datetime.utcnow()
    now = now_utc + timedelta(hours=8)
    y, m, today = now.year, now.month, now.day
    draw.text((20, 10), str(m), font=font_huge, fill=0)
    draw.text((90, 20), now.strftime("%B"), font=font_title, fill=0)
    draw.text((90, 48), str(y), font=font_item, fill=0)
    draw.line([(20, 78), (380, 78)], fill=0, width=2)
    headers = ["日", "一", "二", "三", "四", "五", "六"]
    col_w = 53
    for i, h in enumerate(headers):
        draw.text((25 + i*col_w, 88), h, font=font_small, fill=0)
    calendar.setfirstweekday(calendar.SUNDAY)
    cal = calendar.monthcalendar(y, m)
    curr_y, row_h = 115, 38
    for week in cal:
        for c, day in enumerate(week):
            if day != 0:
                dx = 25 + c * col_w
                if day == today:
                    draw.rounded_rectangle([(dx-3, curr_y-2), (dx+35, curr_y+32)], radius=5, outline=0)
                draw.text((dx+2, curr_y), str(day), font=font_item, fill=0)
                bottom_text = get_lunar_or_festival(y, m, day)
                if bottom_text:
                    if len(bottom_text) > 3:
                        try:
                            font_smaller = ImageFont.truetype(FONT_PATH, 10)
                            draw.text((dx+2, curr_y+18), bottom_text, font=font_smaller, fill=0)
                        except:
                            draw.text((dx+2, curr_y+18), bottom_text[:3], font=font_tiny, fill=0)
                    else:
                        draw.text((dx+2, curr_y+18), bottom_text, font=font_tiny, fill=0)
        curr_y += row_h

    success = push_image(img, 3, mac, device_name)
    return (1, 1) if success else (0, 1)

# --- 混合天气获取（按设备独立） ---
def get_hybrid_weather(city_adcode, wttr_location, city_display):
    result = {
        "city": city_display.split("|")[0].strip(), "weather": "未知", "temp_curr": 0,
        "temp_low": 0, "temp_high": 0, "wind_info": "无数据", "humidity": "0%",
        "feel_temp": "N/A", "sunrise": "--:--", "sunset": "--:--", "forecasts": []
    }

    if not AMAP_KEY:
        print("   ⚠️ 未设置 AMAP_WEATHER_KEY")
        return result

    # 1. 高德实时
    try:
        base_url = f"https://restapi.amap.com/v3/weather/weatherInfo?city={city_adcode}&key={AMAP_KEY}&extensions=base"
        base_resp = requests.get(base_url, timeout=10).json()
        if base_resp.get("status") == "1" and base_resp.get("lives"):
            live = base_resp["lives"][0]
            result["weather"] = live.get("weather", "未知")
            result["temp_curr"] = int(live.get("temperature", 0))
            result["humidity"] = live.get("humidity", "0") + "%"
            wind_power_raw = live.get("windpower", "0")
            wind_direction = live.get("winddirection", "")
            wind_num = re.search(r'\d+', wind_power_raw)
            wind_power = wind_num.group(0) if wind_num else "0"
            result["wind_info"] = f"{wind_power}级 {wind_direction}"
            try:
                wind_speed = int(wind_power)
                if wind_speed <= 1: wind_kmh = 2
                elif wind_speed == 2: wind_kmh = 8
                else: wind_kmh = 15 + (wind_speed - 3) * 7
                feel_temp = result["temp_curr"] - (wind_kmh / 15) if wind_kmh > 5 else result["temp_curr"]
                if int(live.get("humidity", 50)) > 70: feel_temp -= 1
                result["feel_temp"] = f"{round(feel_temp, 1)}°C"
            except:
                result["feel_temp"] = f"{result['temp_curr']}°C"
    except Exception as e:
        print(f"   ❌ 高德实时异常: {e}")

    # 2. 高德预报
    try:
        all_url = f"https://restapi.amap.com/v3/weather/weatherInfo?city={city_adcode}&key={AMAP_KEY}&extensions=all"
        all_resp = requests.get(all_url, timeout=10).json()
        if all_resp.get("status") == "1" and all_resp.get("forecasts"):
            casts = all_resp["forecasts"][0].get("casts", [])
            if len(casts) >= 1:
                result["temp_low"] = int(casts[0].get("nighttemp", 0))
                result["temp_high"] = int(casts[0].get("daytemp", 0))
                for idx in [1, 2]:
                    if idx < len(casts):
                        day = casts[idx]
                        result["forecasts"].append({
                            "date": day.get("date", "")[5:],
                            "weather": day.get("dayweather", "未知"),
                            "temp_low": int(day.get("nighttemp", 0)),
                            "temp_high": int(day.get("daytemp", 0))
                        })
    except Exception as e:
        print(f"   ❌ 高德预报异常: {e}")

    # 3. wttr.in 日出日落
    try:
        wttr_url = f"https://wttr.in/{wttr_location}?format=j1&lang=zh"
        wttr_resp = requests.get(wttr_url, timeout=15).json()
        astro = wttr_resp['weather'][0]['astronomy'][0]
        result["sunrise"] = astro['sunrise']
        result["sunset"] = astro['sunset']
    except Exception as e:
        print(f"   ❌ wttr.in 异常: {e}")

    return result

# --- 任务：天气看板 ---
def task_weather_dashboard(mac, enabled_pages, city_adcode, wttr_location, city_display, device_name):
    if "4" not in enabled_pages:
        return 0, 0

    print(f"   生成 Page 4: 天气 ({city_display})...")
    img = Image.new('1', (400, 300), color=255)
    draw = ImageDraw.Draw(img)

    weather = get_hybrid_weather(city_adcode, wttr_location, city_display)
    if weather["temp_curr"] == 0 and not weather["forecasts"]:
        draw.text((20, 50), "天气数据获取失败，请检查 API Key", font=font_item, fill=0)
        success = push_image(img, 4, mac, device_name)
        return (1, 1) if success else (0, 1)

    draw.text((20, 10), city_display, font=font_title, fill=0)

    now_beijing = datetime.utcnow() + timedelta(hours=8)
    update_time = now_beijing.strftime("%H:%M")
    time_text = f"更新: {update_time}"
    try:
        bbox = draw.textbbox((0, 0), time_text, font=font_small)
        time_width = bbox[2] - bbox[0]
    except:
        time_width = len(time_text) * 8
    draw.text((390 - time_width, 12), time_text, font=font_small, fill=0)

    draw.text((25, 40), f"{weather['temp_curr']}°C", font=font_48, fill=0)
    draw.text((25, 100), f"{weather['temp_low']}°/{weather['temp_high']}°", font=font_item, fill=0)
    draw.text((150, 45), f"{weather['weather']}", font=font_36, fill=0)

    draw.rounded_rectangle([(235, 45), (385, 130)], radius=8, outline=0, fill=0)
    draw.text((255, 56), f"{weather['wind_info']}", font=font_small, fill=255)
    draw.text((255, 80), f"湿度 {weather['humidity']}", font=font_small, fill=255)
    draw.text((255, 104), f"体感 {weather['feel_temp']}", font=font_small, fill=255)

    draw.text((25, 135), f"日出 {weather['sunrise']} 日落 {weather['sunset']}", font=font_item, fill=0)
    draw.line([(20, 160), (380, 160)], fill=0, width=1)

    x_positions = [30, 200]
    for i, day in enumerate(weather['forecasts'][:2]):
        x = x_positions[i]
        draw.text((x, 175), day["date"], font=font_item, fill=0)
        draw.text((x, 200), day["weather"], font=font_item, fill=0)
        draw.text((x, 220), f"{day['temp_low']}°~{day['temp_high']}°", font=font_item, fill=0)

    advice = get_clothing_advice(weather['temp_curr'])
    draw.line([(20, 250), (380, 250)], fill=0, width=1)
    advice_lines = [advice[i:i+18] for i in range(0, len(advice), 18)]
    for i, line in enumerate(advice_lines[:2]):
        draw.text((20, 262 + i*24), f"[衣] {line}", font=font_item, fill=0)

    success = push_image(img, 4, mac, device_name)
    return (1, 1) if success else (0, 1)

# ================= 主程序 =================
if __name__ == "__main__":
    if not API_KEY:
        print("❌ 错误: 请先在 GitHub Secrets 中配置 ZECTRIX_API_KEY")
        exit(1)

    if not AMAP_KEY:
        print("⚠️ 警告: 未配置 AMAP_WEATHER_KEY，天气页面将显示无数据")

    print("=" * 50)
    print("🚀 墨水屏综合看板推送任务启动")
    print(f"📅 {datetime.utcnow() + timedelta(hours=8)}")
    print("=" * 50)

    report = []

    for dev in DEVICES:
        mac = os.environ.get(dev["mac_env"])
        name = dev.get("name", dev["mac_env"])
        pages = [p.strip() for p in dev.get("pages", "").split(",") if p.strip()]
        pages = [p for p in pages if p in ("1", "2", "3", "4")]

        print()
        mac_display = f"***{mac[-4:]}" if mac else "未配置"
        print(f"📱 [{name}] MAC: {mac_display}")

        if not mac:
            print(f"   ⚠️ 环境变量 {dev['mac_env']} 未配置，跳过")
            report.append({"name": name, "status": "跳过", "reason": "未配置MAC"})
            continue

        if not pages:
            print(f"   ⚠️ 未配置推送页面，跳过")
            report.append({"name": name, "status": "跳过", "reason": "未配置页面"})
            continue

        print(f"   配置页面: {', '.join(pages)} | 城市: {dev.get('city_display', '未设置')}")

        ok, total = 0, 0

        s, t = task_hotlist(mac, pages, dev.get("hotlist_source", "baidu"), name)
        ok += s
        total += t

        s, t = task_calendar(mac, pages, name)
        ok += s
        total += t

        s, t = task_weather_dashboard(
            mac, pages,
            dev.get("city_adcode", "330102"),
            dev.get("wttr_location", "Shangcheng,Hangzhou"),
            dev.get("city_display", "杭州"),
            name
        )
        ok += s
        total += t

        status = "✅ 成功" if ok == total else ("⚠️ 部分失败" if ok > 0 else "❌ 失败")
        report.append({"name": name, "status": status, "ok": ok, "total": total})

    print()
    print("=" * 50)
    print("📊 推送汇总报告")
    print("=" * 50)
    for r in report:
        if "ok" in r:
            print(f"   {r['name']}: {r['status']} ({r['ok']}/{r['total']} 页)")
        else:
            print(f"   {r['name']}: {r['status']} - {r.get('reason', '')}")
    print("=" * 50)
    print("🎉 任务执行完毕")
