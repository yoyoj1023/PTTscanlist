"""
o1

1st shot
請用 python 撰寫可以直接執行的PTT網軍偵測程式(包含if name == "main": main()的內容)

功能：
一、爬蟲蒐集在 PTT 政黑板的距今近期1週內的文章(包含所有使用者ID的推文)

二、進行資料分析，從中篩濾出可能的網軍相關ID名單(判斷它是否是網軍的邏輯包含但不限於：1. 帳號在短時間內(或較少篇)於特定議題與其他特定帳號成群出沒。
2. 相同的帳號群與特定關鍵字「壯世代」高度關聯。)

三、最後在程式內輸出解釋這些相關ID可能是網軍的原因與可疑活動，並且列出該可疑帳號的相關推文內容。

補充說明：
1.初始化爬蟲僅在首次執行時須開啟，之後要再次反覆執行時可以註解掉，因為爬蟲的動作沒有必要在每次執行時都去請求 PTT的伺服端造成成本浪費

2nd shot
幫我添加一段程式：最後在程式內輸出，統計一共有多少可疑ID，並將可疑ID進行排行
"""

import requests
from bs4 import BeautifulSoup
import re
import datetime
import time
from collections import defaultdict

# =====================================
#           全域設定參數
# =====================================
PTT_URL = 'https://www.ptt.cc'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/88.0.4324.150 Safari/537.36'
}
COOKIES = {'over18': '1'}  # PTT 成人版的驗證


# =====================================
#            爬蟲函式區
# =====================================
def get_web_page(url):
    """對目標 URL 送出 GET 請求，回傳網頁 HTML 文字內容。"""
    try:
        resp = requests.get(url, headers=HEADERS, cookies=COOKIES, timeout=5)
        if resp.status_code == 200:
            return resp.text
        else:
            print(f"無法取得網頁，狀態碼: {resp.status_code}")
    except Exception as e:
        print(f"Request 發生錯誤: {e}")
    return None


def get_articles_on_page(dom):
    """
    傳入該頁面的 HTML（BeautifulSoup 物件），
    解析本頁所有文章的標題、連結以及日期資訊。
    回傳列表，每個元素為 dict:
        {
            'title': '文章標題',
            'link': '文章連結(相對路徑)',
            'date': '月/日'
        }
    """
    articles = []
    divs = dom.find_all('div', class_='r-ent')
    for d in divs:
        # 文章標題
        title_tag = d.find('div', class_='title').find('a')
        if title_tag:
            title = title_tag.text.strip()
            link = title_tag['href']

            # 推測列表頁中的日期(格式為 'X/M' 或 ' M/D' 等)，僅作輔助使用
            date_tag = d.find('div', class_='date')
            date_str = date_tag.text.strip() if date_tag else ''

            articles.append({
                'title': title,
                'link': link,
                'date': date_str
            })
    return articles


def parse_article_content(article_url):
    """
    傳入文章連結(完整 URL)，抓取文章內文與推文資訊。
    回傳 dict:
        {
            'title': 文章標題,
            'author': 作者ID,
            'date': 發文完整日期(可能需從內文抓取),
            'pushes': [
                {
                    'push_tag': '推/噓/→',
                    'user_id': 推文者ID,
                    'content': 推文內文,
                    'time': 推文時間
                },
                ...
            ]
        }
    """
    page_html = get_web_page(article_url)
    if page_html is None:
        return None

    soup = BeautifulSoup(page_html, 'html.parser')
    main_content = soup.find(id='main-content')
    if not main_content:
        return None

    # 先抓取標題、作者、時間等
    meta_lines = main_content.find_all('div', class_='article-metaline')
    author, title, date_str = None, None, None

    for m in meta_lines:
        meta_tag = m.find('span', 'article-meta-tag')
        meta_value = m.find('span', 'article-meta-value')
        if not meta_tag or not meta_value:
            continue
        if meta_tag.text == '作者':
            author = meta_value.text
        elif meta_tag.text == '標題':
            title = meta_value.text
        elif meta_tag.text == '時間':
            date_str = meta_value.text

    # 移除 meta 整塊
    for m in meta_lines:
        m.decompose()
    meta_right = main_content.find_all('div', class_='article-metaline-right')
    for m in meta_right:
        m.decompose()

    # 取得推文
    pushes = []
    push_tags = main_content.find_all('div', class_='push')
    for p in push_tags:
        push_tag = p.find('span', class_='push-tag').text.strip() if p.find('span', class_='push-tag') else ''
        user_id = p.find('span', class_='push-userid').text.strip() if p.find('span', class_='push-userid') else ''
        content = p.find('span', class_='push-content').text.strip(': ').strip() if p.find('span',
                                                                                           class_='push-content') else ''
        push_time = p.find('span', class_='push-ipdatetime').text.strip() if p.find('span',
                                                                                    class_='push-ipdatetime') else ''

        pushes.append({
            'push_tag': push_tag,
            'user_id': user_id,
            'content': content,
            'time': push_time
        })

    return {
        'title': title,
        'author': author,
        'date': date_str,
        'pushes': pushes
    }


def crawl_hatepolitics_data(days=7, max_pages=10):
    """
    爬取 PTT 政黑板 近 days 天內的文章（限制抓取 max_pages 頁）。
    回傳列表，元素為文章的詳細推文資訊。
    """
    base_url = f"{PTT_URL}/bbs/HatePolitics/index.html"
    articles_data = []
    page_count = 0

    now = datetime.datetime.now()
    deadline = now - datetime.timedelta(days=days)

    # 先抓取第一頁
    current_page_html = get_web_page(base_url)
    if not current_page_html:
        print("無法抓取起始頁面")
        return articles_data

    while page_count < max_pages:
        soup = BeautifulSoup(current_page_html, 'html.parser')
        articles = get_articles_on_page(soup)

        # 取得 [上頁] 連結
        btn_group = soup.find('div', class_='btn-group btn-group-paging')
        if not btn_group:
            break
        prev_link_tag = btn_group.find_all('a')[1]  # 一般來說 [上頁, 下頁, 最新, 返回看板列表]
        if not prev_link_tag or 'href' not in prev_link_tag.attrs:
            break
        prev_page_url = PTT_URL + prev_link_tag['href']

        # 逐篇文章檢查日期是否在一週內
        for art in articles:
            article_link = art['link']
            # 過濾非本板連結
            if not article_link.startswith('/bbs/HatePolitics'):
                continue

            full_url = PTT_URL + article_link
            article_content = parse_article_content(full_url)
            if not article_content:
                continue

            # 嘗試解析文章時間
            article_date_str = article_content['date']  # e.g. "Sun Jan 22 11:23:45 2025"
            if article_date_str:
                try:
                    article_time = datetime.datetime.strptime(article_date_str, '%a %b %d %H:%M:%S %Y')
                except ValueError:
                    article_time = now
            else:
                article_time = now

            if article_time >= deadline:
                articles_data.append(article_content)
            else:
                # 若超過一週，後面更舊的不看
                break

        # 進入下一頁
        page_count += 1
        current_page_html = get_web_page(prev_page_url)
        if not current_page_html:
            break

    return articles_data


# =====================================
#            分析函式區
# =====================================

def analyze_data(articles_data):
    """
    根據爬回來的 articles_data 做簡易的「網軍」可疑度判斷。
    邏輯(示範)：
      1. 在多篇文章中同時出現與同伴共推的頻率
      2. 推文中提及關鍵字「壯世代」的次數
    最後回傳 suspicious_ids = {
      '某ID': {
        'reason': '理由說明',
        'pushes': [ (文章標題, 推文內容), ... ],
        'score': ... (用於排行)
      },
      ...
    }
    """
    # 紀錄每篇文章的推文 ID set
    article_id_sets = []
    # 紀錄各 ID 推文紀錄: ID -> [ (文章標題, 推文內容), ... ]
    user_push_records = defaultdict(list)

    # (article_title) -> [ (user_id, push_content), ... ]
    article_push_map = defaultdict(list)

    for art in articles_data:
        title = art.get('title', 'No Title')
        pushes = art.get('pushes', [])
        id_set = set()
        for push in pushes:
            user_id = push['user_id']
            content = push['content']
            id_set.add(user_id)
            article_push_map[title].append((user_id, content))
            user_push_records[user_id].append((title, content))
        article_id_sets.append(id_set)

    # 計算 ID 與其他人同篇共現次數
    id_co_occurrence = defaultdict(lambda: defaultdict(int))
    for id_set in article_id_sets:
        for uid1 in id_set:
            for uid2 in id_set:
                if uid1 != uid2:
                    id_co_occurrence[uid1][uid2] += 1

    # 計算關鍵字例如「壯世代」提及次數
    mention_keyword = defaultdict(int)
    keyword = "壯世代"
    for uid, records in user_push_records.items():
        for (title, content) in records:
            if keyword in content:
                mention_keyword[uid] += 1

    # 開始判斷可疑
    suspicious_ids = {}
    for uid, co_dict in id_co_occurrence.items():
        # 找出跟 uid 同時出現 >= 3 次的其他 ID
        frequent_partners = [other_id for other_id, count in co_dict.items() if count >= 3]
        keyword_count = mention_keyword[uid]

        # 簡單設定: 若同時出現 >=3 次的「夥伴」數量>=2 或 關鍵字次數>=2 就列為可疑
        if len(frequent_partners) >= 2 or keyword_count >= 2:
            reason_list = []
            if len(frequent_partners) >= 2:
                reason_list.append(
                    f"在多篇文章中經常與以下帳號同時出沒: {', '.join(frequent_partners)}"
                )
            if keyword_count >= 2:
                reason_list.append(
                    f"於推文中多次提及關鍵字「{keyword}」(共 {keyword_count} 次)"
                )
            reason_desc = "，且".join(reason_list)

            # 設計一個簡易「可疑分數」，例如： (夥伴數量 + 關鍵字次數)
            score = len(frequent_partners) + keyword_count

            suspicious_ids[uid] = {
                'reason': reason_desc,
                'pushes': user_push_records[uid],
                'score': score
            }

    return suspicious_ids


# =====================================
#             主程式入口
# =====================================
def main():
    # 第一次執行可以啟用爬蟲，後續若已爬過可將這段註解改為讀本地快取
    print("開始爬取 PTT 政黑板 近一週文章...")
    articles_data = crawl_hatepolitics_data(days=7, max_pages=10)
    print(f"共取得 {len(articles_data)} 篇文章的推文資料。")

    # 進行可疑帳號分析
    print("進行可疑帳號分析...")
    suspicious_ids = analyze_data(articles_data)

    # 根據「score」進行排序
    if suspicious_ids:
        # 先把可疑ID依照 score(由大到小) 排序
        suspicious_list = sorted(suspicious_ids.items(), key=lambda x: x[1]['score'], reverse=True)
        suspicious_count = len(suspicious_list)

        print(f"\n=== 以下為偵測到的可疑帳號，共 {suspicious_count} 位 ===")
        print("=== 依可疑分數(示範)由高到低進行排行 ===")

        for rank, (uid, info) in enumerate(suspicious_list, start=1):
            print(f"\n[排行 #{rank}] 可疑ID: {uid} (可疑分數: {info['score']})")
            print(f"  -> 可疑原因: {info['reason']}")
            print("  -> 以下為該ID的相關推文記錄：")
            for (art_title, push_content) in info['pushes']:
                print(f"     - [{art_title}] {push_content}")
    else:
        print("\n未發現符合條件的可疑帳號。")


if __name__ == "__main__":
    main()
