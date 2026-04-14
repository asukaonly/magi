"""Locale display-name mappings for reverse geocoder results.

Each mapping is keyed by ``{country_code}:{admin1_code}`` as found in the
GeoNames ``admin1`` column.  Values are the vernacular region name suitable
for display alongside the city name produced by :func:`geocoder.format_location`.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Chinese administrative divisions  (GeoNames admin1 codes for CN)
# ---------------------------------------------------------------------------
_ZH_CN: dict[str, str] = {
    # Municipalities (直辖市)
    "CN:22": "北京市",
    "CN:23": "上海市",
    "CN:28": "天津市",
    "CN:33": "重庆市",
    # Provinces (省)
    "CN:01": "安徽省",
    "CN:07": "福建省",
    "CN:15": "甘肃省",
    "CN:30": "广东省",
    "CN:16": "广西壮族自治区",
    "CN:18": "贵州省",
    "CN:31": "海南省",
    "CN:10": "河北省",
    "CN:08": "黑龙江省",
    "CN:09": "河南省",
    "CN:11": "湖北省",
    "CN:12": "湖南省",
    "CN:19": "江苏省",
    "CN:03": "江西省",
    "CN:21": "吉林省",
    "CN:24": "辽宁省",
    "CN:20": "内蒙古自治区",
    "CN:26": "宁夏回族自治区",
    "CN:29": "青海省",
    "CN:32": "山东省",
    "CN:02": "山西省",
    "CN:25": "陕西省",
    "CN:06": "四川省",
    "CN:14": "西藏自治区",
    "CN:13": "新疆维吾尔自治区",
    "CN:27": "云南省",
    "CN:04": "浙江省",
    # SARs (特别行政区)
    "HK:00": "香港",
    "MO:00": "澳门",
    # Taiwan (省)
    "TW:04": "台北市",
    "TW:02": "高雄市",
    "TW:03": "台中市",
    "TW:05": "台南市",
    # Japan (都道府県)
    "JP:40": "東京都",
    "JP:27": "大阪府",
    "JP:14": "神奈川県",
    "JP:23": "愛知県",
    "JP:26": "京都府",
    "JP:13": "東京都",
    "JP:28": "兵庫県",
    "JP:01": "北海道",
    "JP:34": "広島県",
    "JP:40": "福岡県",
    # South Korea (도/시)
    "KR:11": "首尔特别市",
    "KR:26": "釜山广域市",
    "KR:28": "仁川广域市",
    "KR:41": "京畿道",
    # Singapore
    "SG:00": "新加坡",
    # Common international (Chinese display names)
    "US:CA": "加利福尼亚州",
    "US:NY": "纽约州",
    "US:TX": "德克萨斯州",
    "US:WA": "华盛顿州",
    "US:MA": "马萨诸塞州",
    "US:IL": "伊利诺伊州",
    "US:FL": "佛罗里达州",
    "US:HI": "夏威夷州",
    "GB:ENG": "英格兰",
    "GB:SCT": "苏格兰",
    "FR:IDF": "法兰西岛",
    "FR:75": "法兰西岛",
    "FR:11": "法兰西岛",
    "DE:BE": "柏林州",
    "DE:BY": "巴伐利亚州",
    "DE:16": "柏林",
    "DE:02": "巴伐利亚",
    "IT:25": "伦巴第",
    "IT:09": "托斯卡纳",
    "AU:02": "新南威尔士州",
    "AU:07": "维多利亚州",
    "CA:08": "安大略省",
    "CA:02": "不列颠哥伦比亚省",
    "TH:10": "曼谷",
    "VN:SG": "胡志明市",
    "VN:44": "河内",
    "MY:14": "吉隆坡",
}

LOCALE_MAPS: dict[str, dict[str, str]] = {
    "zh-CN": _ZH_CN,
    "zh": _ZH_CN,
}


def get_locale_map(locale: str) -> dict[str, str] | None:
    """Return the locale map for the given locale code, or ``None``."""
    return LOCALE_MAPS.get(locale) or LOCALE_MAPS.get(locale.split("-")[0] if "-" in locale else "")
