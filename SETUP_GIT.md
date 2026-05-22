# 配置 Git + GitHub SSH 推送

## 1. 配置 git 身份

```bash
git config --global user.name "你的名字"
git config --global user.email "你的GitHub邮箱"
```

## 2. 生成 SSH key

```bash
ssh-keygen -t ed25519 -C "你的GitHub邮箱"
```

一路回车，key 保存在 `~/.ssh/id_ed25519`

## 3. 复制公钥

```bash
cat ~/.ssh/id_ed25519.pub
```

复制输出的全部内容（以 `ssh-ed25519` 开头）

## 4. 添加到 GitHub

1. 打开 https://github.com/settings/ssh/new
2. Title 随便填（如 `my-server`）
3. Key type 选 `Authentication Key`
4. Key 粘贴第 3 步复制的内容
5. 点 Add SSH key

## 5. 测试连接

```bash
ssh -T git@github.com
```

看到 `Hi SkonJIYHD! You've successfully authenticated` 表示成功

## 6. 切换远程地址为 SSH

```bash
cd /mnt/Data_disk/project/LifeSimulation
git remote set-url origin git@github.com:SkonJIYHD/LifeSimulationPlugin.git
```

## 7. 推送

```bash
git push origin main
```

---

之后每次推送直接 `git push` 即可，不需要再输密码。
