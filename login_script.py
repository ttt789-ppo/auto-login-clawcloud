# 文件名: login_script.py
# 作用: 自动登录 ClawCloud Run，支持 GitHub 账号密码 + 2FA 自动验证

import os
import time
import pyotp  # 引入 pyotp 库，用于根据你的密钥生成动态的 6 位数验证码
from playwright.sync_api import sync_playwright # 引入 playwright，用于模拟真人操作浏览器

def run_login():
    # 1. 获取环境变量中的敏感信息 (从 GitHub Secrets 中读取)
    username = os.environ.get("GH_USERNAME")
    password = os.environ.get("GH_PASSWORD")
    totp_secret = os.environ.get("GH_2FA_SECRET")

    # 检查账号密码有没有配置，如果没有直接报错并停止运行
    if not username or not password:
        print("❌ 错误: 必须设置 GH_USERNAME 和 GH_PASSWORD 环境变量。")
        return

    print("🚀 [Step 1] 启动浏览器...")
    with sync_playwright() as p:
        # 启动 Chromium 浏览器 
        # (headless=True 表示无头模式，也就是在后台静默运行，不弹出真实窗口，适合服务器)
        browser = p.chromium.launch(headless=True)
        # 设置常见的大屏幕分辨率，防止网页变成手机版导致按钮错位找不到
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # 2. 访问 ClawCloud 控制台登录页
        target_url = "https://ap-northeast-1.run.claw.cloud/"
        print(f"🌐 [Step 2] 正在访问: {target_url}")
        page.goto(target_url)
        # 暂停等待，直到网页的网络请求变少，确保页面基本加载完成
        page.wait_for_load_state("networkidle")

        # 3. 点击 GitHub 登录按钮 【重要修改：升级了寻找按钮的逻辑】
        print("🔍 [Step 3] 寻找 GitHub 按钮...")
        try:
            # 策略 A：精确寻找网页上文本内容就是 "GitHub" 的元素（不管它是不是 button 标签）
            login_button = page.get_by_text("GitHub", exact=True)
            
            # 策略 B：如果策略 A 没找到（数量为0），尝试找带有链接 <a> 且包含 "GitHub" 文字的元素
            if login_button.count() == 0:
                login_button = page.locator("a:has-text('GitHub')")
                
            # 策略 C：如果还是没找到，退回到原来的老办法，找 <button> 标签
            if login_button.count() == 0:
                login_button = page.locator("button:has-text('GitHub')")

            # 等待我们匹配到的第一个元素在屏幕上显示出来（可见状态），最多等 10 秒
            login_button.first.wait_for(state="visible", timeout=10000)
            # 点击这个按钮
            login_button.first.click()
            print("✅ 按钮已点击")
        except Exception as e:
            print(f"⚠️ 未找到 GitHub 按钮 (可能已自动登录或页面变动): {e}")

        # 4. 处理 GitHub 登录表单
        print("⏳ [Step 4] 等待跳转到 GitHub...")
        try:
            # 观察浏览器的 URL 地址栏，等待它变更为包含 github.com，最多等 15 秒
            page.wait_for_url(lambda url: "github.com" in url, timeout=15000)
            
            # 如果 URL 里有 login，说明正好卡在输入账号密码的页面
            if "login" in page.url:
                print("🔒 输入账号密码...")
                # 寻找网页上 ID 为 login_field 的输入框，填入账号
                page.fill("#login_field", username)
                # 寻找 ID 为 password 的输入框，填入密码
                page.fill("#password", password)
                # 寻找名字叫 commit 的提交按钮并点击
                page.click("input[name='commit']") 
                print("📤 登录表单已提交")
        except Exception as e:
            # 如果不需要填密码（比如 GitHub 记住了登录状态），就跳过
            print(f"ℹ️ 跳过账号密码填写 (可能已自动登录): {e}")

        # 5. 【核心】处理 2FA 双重验证 (解决异地登录被风控拦截的问题)
        # 给网页 3 秒钟的跳转反应时间
        page.wait_for_timeout(3000)
        
        # 检查 URL 是否包含 two-factor 关键词，或者页面上有没有出现验证码专用的输入框
        if "two-factor" in page.url or page.locator("#app_totp").count() > 0:
            print("🔐 [Step 5] 检测到 2FA 双重验证请求！")
            
            if totp_secret:
                print("🔢 正在计算动态验证码 (TOTP)...")
                try:
                    # 使用你提供的 2FA 密钥，生成此时此刻的 6 位数字验证码
                    totp = pyotp.TOTP(totp_secret)
                    token = totp.now()
                    print(f"   生成的验证码: {token}")
                    
                    # 填入 GitHub 的验证码输入框 (它的网页 ID 通常是 app_totp)
                    page.fill("#app_totp", token)
                    print("✅ 验证码已填入，GitHub 应会自动跳转...")
                    
                except Exception as e:
                    print(f"❌ 填入验证码失败: {e}")
            else:
                # 如果遇到双重验证但没有密钥，程序没法继续，只能报错退出
                print("❌ 致命错误: 检测到 2FA 但未配置 GH_2FA_SECRET Secret！")
                exit(1)

        # 6. 处理授权确认页 (Authorize App)
        # 第一次通过某个应用登录 GitHub，可能会弹出一个绿色按钮问你是否授权
        page.wait_for_timeout(3000)
        if "authorize" in page.url.lower():
            print("⚠️ 检测到授权请求，尝试点击 Authorize...")
            try:
                # 尝试点击授权按钮，最多等 5 秒
                page.click("button:has-text('Authorize')", timeout=5000)
            except:
                pass

        # 7. 等待最终跳转结果
        print("⏳ [Step 6] 等待跳转回 ClawCloud 控制台 (约20秒)...")
        # 这里强制让程序“睡” 20 秒，因为网页重定向并完全加载出控制台画面需要比较长的时间
        page.wait_for_timeout(20000)
        
        final_url = page.url
        print(f"📍 最终页面 URL: {final_url}")
        
        # 【排错关键】在此刻进行截图保存！无论成败都能看到最后卡在哪个画面
        page.screenshot(path="login_result.png")
        print("📸 已保存结果截图: login_result.png")

        # 8. 验证是否成功登录进去了
        # 默认先把成功状态设为 False (假)
        is_success = False
        
        # 检查点 A: 页面上出现了登录后才有的文字（最准确的判断方式）
        if page.get_by_text("App Launchpad").count() > 0 or page.get_by_text("Devbox").count() > 0:
            is_success = True
        # 检查点 B: URL 包含了后台控制台的特征单词
        elif "private-team" in final_url or "console" in final_url:
            is_success = True
        # 检查点 C: 只要现在的页面不是最初的登录页，也不是 GitHub 验证页，通常也是成功了
        elif "signin" not in final_url and "github.com" not in final_url:
            is_success = True

        if is_success:
            print("🎉🎉🎉 登录成功！任务完成。")
        else:
            print("😭😭😭 登录失败。请下载 login_result.png 查看原因。")
            # exit(1) 意味着抛出错误代码 1，这会让 GitHub Actions 把这次任务标记为失败（红色）
            exit(1) 

        # 运行结束，关闭模拟浏览器，释放服务器内存
        browser.close()

# Python 的标准写法：如果这个脚本是被直接运行的，就开始执行 run_login() 函数
if __name__ == "__main__":
    run_login()
