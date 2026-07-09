import psutil
import time
import os

def safe_fill_memory(usage_target=0.90):
    """
    占用内存到目标百分比，保留一部分给系统
    usage_target: 目标内存使用率 (默认90%)
    """
    memory_blocks = []
    
    while True:
        mem = psutil.virtual_memory()
        current_usage = mem.percent / 100.0
        
        print(f"当前内存使用率: {mem.percent:.1f}% | "
              f"已用: {mem.used/1024**3:.1f}GB | "
              f"可用: {mem.available/1024**3:.1f}GB")
        
        if current_usage < usage_target:
            # 计算还需要分配多少
            need_bytes = int((usage_target - current_usage) * mem.total)
            # 每次分配50MB，避免一次性太猛
            alloc_size = min(50 * 1024 * 1024, need_bytes)
            
            block = bytearray(alloc_size)
            for i in range(0, alloc_size, 4096):
                block[i] = 1
            memory_blocks.append(block)
            
        else:
            print(f"✅ 已达到目标使用率 {usage_target*100:.0f}%，保持中...")
            time.sleep(30)
            
            # 定期刷新防止被回收
            for block in memory_blocks:
                block[0] ^= 1

        time.sleep(1)

if __name__ == "__main__":
    print(f"PID: {os.getpid()}")
    # 占用到90%，保留10%给系统和其他程序
    safe_fill_memory(usage_target=0.90)