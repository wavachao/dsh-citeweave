**HDD 与 SSD：结构决定表现**

**一、内部结构与工作方式**

HDD 是机电设备：铝或玻璃盘片（platter）固定在主轴（spindle）上，以 5400–7200 转/分高速旋转；读写磁头装在执行臂上，由音圈马达驱动，在盘片上方约 5–10 纳米处“飞”过，通过改变磁畴方向记录 0/1。数据按同心磁道、扇区排布，寻址时必须先等盘片转到目标位置，再把磁头移到目标磁道。[来源：Stellarinfo](https://www.stellarinfo.co.in/hdd/key-components-of-hard-drive.php)

![HDD 与 SSD 内部结构对比示意图](https://media.geeksforgeeks.org/wp-content/uploads/20250317145546163469/Difference-Between-HSS-and-SSD.webp)

SSD 是全电子器件：主控芯片、NAND 闪存颗粒和缓存组成阵列，靠电荷存储数据，没有转轴和磁头。[来源：GeeksforGeeks](https://www.geeksforgeeks.org/computer-organization-architecture/difference-between-hard-disk-drive-hdd-and-solid-state-drive-ssd/) NAND 按块擦除、按页写入，因此写入时需要“读—改—写”，并由磨损均衡算法把擦写分摊到全片。

![HDD 内部部件：盘片、主轴、磁头组件与电路板](https://www.stellarinfo.co.in/image/catalog/knowledge-base/service/inside-hdd/HDD_Stellar.jpg)

**二、对随机读取的影响**

HDD 的每次随机读取都要付出两笔物理代价：把磁头移到目标磁道需要几毫秒，等旋转到目标扇区又需要几毫秒，所以随机 IOPS 通常只有一两百。SSD 依靠地址直接访问闪存颗粒并多通道并行，延迟在数十到上百微秒量级，随机读取 IOPS 可高出几个数量级。连续读取时两者差距较小（HDD 约 200–500 MB/s，SSD 可达数千 MB/s 以上）。[来源：IBM](https://www.ibm.com/think/topics/hard-disk-drive-vs-solid-state-drive)

**三、对寿命的影响**

HDD 的寿命主要取决于机械磨损和磁头碰撞风险。它内置冲击传感器，掉落后会自动收回磁头，以保护盘片；但如果盘片或磁头损坏，数据仍可能通过更换部件在无尘室中抢救出来。SSD 没有机械部件，耐摔、静音、省电，但寿命受擦写次数（TBW）限制，主要依靠磨损均衡和留用备用块来延长使用时间；一旦主控或颗粒故障，恢复难度通常更大。此外，SSD 长期断电存在电荷缓慢流失的风险。[来源：IBM](https://www.ibm.com/think/topics/hard-disk-drive-vs-solid-state-drive)

**简要结论**：HDD 随机读取慢，最怕物理冲击，但每 GB 成本低、大容量下断电保存更稳定；SSD 随机读取快、抗震好，适合系统盘和频繁读写场景，但要通过磨损均衡来保障寿命。