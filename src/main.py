import os
import requests
import logging
import time
import random
import json
from pathlib import Path
from seting import *

# 确保必要目录存在
Path(image_path).mkdir(parents=True, exist_ok=True)
log_dir = Path(os.path.dirname(os.path.join(image_path, 'comic_downloader.log')))
log_dir.mkdir(parents=True, exist_ok=True)

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 索引文件路径
INDEX_FILE = Path(image_path) / "indexs.json"

def format_str(s, base="04"):
    s = str(s)
    l = len(s)
    if l >= int(base[1]):
        return s
    return base[0] * (int(base[1]) - l) + s

def get_comic_target_dir(index: int) -> Path:
    """计算漫画的目标目录路径"""
    group_1000_start = ((index - 1) // 1000) * 1000 + 1
    group_1000_end = group_1000_start + 999
    group_100_start = group_1000_start + ((index - group_1000_start) // 100) * 100
    group_100_end = group_100_start + 99
    group_10_start = group_100_start + ((index - group_100_start) // 10) * 10
    group_10_end = group_10_start + 9
    
    return (
        Path(image_path) 
        / f"{group_1000_start:04}-{group_1000_end:04}" 
        / f"{group_100_start:04}-{group_100_end:04}"
        / f"{group_10_start:04}-{group_10_end:04}"
        / f"{format_str(index)}"
    )

def get_md_path(index: int) -> Path:
    """获取漫画的Markdown文件路径"""
    return get_comic_target_dir(index) / f"{format_str(index)}.md"

def load_index():
    """加载索引文件"""
    if INDEX_FILE.exists():
        try:
            with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"newest": 0, "lack": []}

def save_index(index_data):
    """保存索引文件"""
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index_data, f, indent=2)

def download_image(image_url: str, target_path: Path):
    """下载并保存图片"""
    try:
        response = requests.get(image_url, stream=True)
        response.raise_for_status()
        
        with open(target_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logging.info(f"已下载图片到 {target_path}")
        return True
    except Exception as e:
        logging.error(f"下载图片失败: {image_url}, 错误: {str(e)}")
        return False

def download_single_comic(index: int, index_data):
    """下载单个漫画并更新索引"""
    url_template = 'https://xkcd.com/{}/info.0.json'
    
    try:
        response = requests.get(url_template.format(index))
        response.raise_for_status()
        comic = response.json()
        
        # 计算目标目录
        target_dir = get_comic_target_dir(index)
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # 下载图片
        image_url = comic['img']
        image_name = f"{format_str(index)}-{os.path.basename(image_url)}"
        image_path_local = target_dir / image_name
        
        # 创建Markdown文件
        md_content = (
            stencil
            .replace("$image$", image_url)
            .replace("$url$", f"{xkcd_url}/{index}")
            .replace("$title$", comic['title'])
            .replace("$index$", str(index))
        )
        
        md_path = target_dir / f"{format_str(index)}.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        # 下载图片
        if not image_path_local.exists():
            if not download_image(image_url, image_path_local):
                # 下载失败，添加到缺失列表
                if index not in index_data["lack"]:
                    index_data["lack"].append(index)
                return False
        
        # 更新最新漫画编号
        if index > index_data["newest"]:
            index_data["newest"] = index
            
        # 如果之前缺失，现在成功下载则移除
        if index in index_data["lack"]:
            index_data["lack"].remove(index)
            
        logging.info(f"成功下载漫画 {index}: {comic['title']}")
        return True
        
    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            logging.warning(f"漫画编号 {index} 不存在")
        else:
            logging.error(f"请求漫画编号 {index} 时出错: {e}")
    except Exception as e:
        logging.error(f"处理漫画编号 {index} 时发生错误: {str(e)}")
    
    # 下载失败，添加到缺失列表
    if index not in index_data["lack"]:
        index_data["lack"].append(index)
    return False

def download_new_comics(index_data, count=20):
    """下载新漫画"""
    start_number = index_data["newest"]
    downloaded = 0
    failures = 0
    
    for i in range(start_number + 1, start_number + count + 1):
        success = download_single_comic(i, index_data)
        if success:
            downloaded += 1
        else:
            failures += 1
        
        # 保存索引以防中断
        save_index(index_data)
        time.sleep(sleep_time)
        
        # 如果连续失败太多，提前结束
        if failures >= 5 and failures > downloaded:
            logging.warning("连续失败过多，提前终止下载")
            break
    
    logging.info(f"下载完成: 成功 {downloaded} 个, 失败 {failures} 个")
    return downloaded

def retry_failed_comics(index_data):
    """尝试重新下载之前失败的漫画"""
    if not index_data["lack"]:
        return 0
    
    logging.info(f"发现 {len(index_data['lack'])} 个之前失败的漫画，尝试重新下载...")
    
    # 复制缺失列表，避免修改过程中迭代
    failed_list = index_data["lack"].copy()
    retry_success = 0
    
    for index in failed_list:
        success = download_single_comic(index, index_data)
        if success:
            retry_success += 1
        
        save_index(index_data)
        time.sleep(sleep_time)
    
    logging.info(f"重新下载完成: 成功 {retry_success} 个")
    return retry_success

def get_random_comic_path(max_index, index_data, retries=5):
    """获取随机漫画的Markdown文件路径"""
    for _ in range(retries):
        # 在1到最大索引之间随机选择
        rand_index = random.randint(1, max_index)
        
        # 跳过缺失的漫画
        if rand_index in index_data["lack"]:
            continue
            
        # 获取文件路径
        md_path = get_md_path(rand_index)
        if md_path.exists():
            return md_path
    
    return None

def pick_and_generate_readme(index_data):
    """生成 README.md"""
    # 获取最新漫画
    newest_index = index_data["newest"]
    if newest_index == 0:
        logging.warning("没有可用的漫画，无法生成 README.md")
        return
    
    # 获取最新漫画的Markdown内容
    latest_md_path = get_md_path(newest_index)
    if not latest_md_path.exists():
        logging.error(f"最新漫画 {newest_index} 的Markdown文件不存在")
        return
    
    with open(latest_md_path, 'r', encoding='utf-8') as f:
        latest_content = f.read()
    
    # 获取三个随机漫画的内容
    random_contents = []
    for _ in range(3):
        rand_path = get_random_comic_path(newest_index, index_data)
        if rand_path:
            with open(rand_path, 'r', encoding='utf-8') as f:
                random_contents.append(f.read())
        else:
            random_contents.append("")
    
    # 准备替换内容
    replacements = {
        "$new$": latest_content,
        "$random1$": random_contents[0] if len(random_contents) > 0 else "",
        "$random2$": random_contents[1] if len(random_contents) > 1 else "",
        "$random3$": random_contents[2] if len(random_contents) > 2 else ""
    }
    
    # 生成README内容
    readme_content = stencil_readme
    for key, value in replacements.items():
        readme_content = readme_content.replace(key, value)

    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    logging.info(f"已生成 README.md，最新漫画: {newest_index}")

if __name__ == "__main__":
    # 加载索引
    index_data = load_index()
    logging.info(f"加载索引: 最新漫画 {index_data['newest']}, 缺失 {len(index_data['lack'])} 个")
    
    # 重试之前失败的漫画
    retry_failed_comics(index_data)
    
    # 下载新漫画
    download_new_comics(index_data, count=max_once)
    
    # 保存最终索引
    save_index(index_data)
    
    # 生成README
    pick_and_generate_readme(index_data)