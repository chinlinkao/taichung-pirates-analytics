# -*- coding: utf-8 -*-
import urllib.request
import re
import time

BASE_URL = 'https://myscore.games'
INDEX_URL = 'https://myscore.games/index.php'

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.read().decode('utf-8')

def get_links_from_html(html, base=''):
    pattern = r'<a\s[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>'
    links = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
    result = []
    for href, text in links:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        # Make absolute URL
        if href.startswith('http'):
            full_url = href
        elif href.startswith('/'):
            full_url = BASE_URL + href
        else:
            full_url = base + '/' + href
        result.append((full_url, clean_text))
    return result

print('正在抓取主頁面...')
index_html = fetch(INDEX_URL)

# Get all game links from index page
game_links = re.findall(r'href=["\']([^"\']*game_id=\d+)["\']', index_html)
game_links = list(set(game_links))
game_links = [BASE_URL + l if l.startswith('/') else l for l in game_links]

print(f'找到 {len(game_links)} 個比賽連結，開始逐一抓取...')

pirate_links = {}

for i, game_url in enumerate(sorted(game_links)):
    try:
        print(f'  [{i+1}/{len(game_links)}] {game_url}')
        html = fetch(game_url)
        all_links = get_links_from_html(html, BASE_URL)
        for url, text in all_links:
            if 'show_text.php' in url:
                continue
            if '海盜' in text:
                if url not in pirate_links:
                    pirate_links[url] = text
                    print(f'    >>> 找到: {text} -> {url}')
        time.sleep(0.3)
    except Exception as e:
        print(f'    錯誤: {e}')

# Also check index page itself
all_links = get_links_from_html(index_html, BASE_URL)
for url, text in all_links:
    if 'show_text.php' in url:
        continue
    if '海盜' in text:
        if url not in pirate_links:
            pirate_links[url] = text

print(f'\n共找到 {len(pirate_links)} 個含有「海盜」的連結')

# Save to file
output_file = '海盜隊超連結.txt'
with open(output_file, 'w', encoding='utf-8') as f:
    f.write('myscore.games 網站中含有「海盜」的球隊超連結\n')
    f.write(f'來源: {INDEX_URL}\n')
    f.write('=' * 60 + '\n\n')
    f.write(f'共找到 {len(pirate_links)} 個連結\n\n')
    for i, (url, text) in enumerate(sorted(pirate_links.items(), key=lambda x: x[1]), 1):
        f.write(f'{i}. {text}\n')
        f.write(f'   {url}\n\n')

print(f'結果已儲存至: {output_file}')
