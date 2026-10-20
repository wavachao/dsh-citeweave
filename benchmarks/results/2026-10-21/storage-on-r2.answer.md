**一句话概括：HDD（机械硬盘）靠盘片旋转和磁头移动读写数据，SSD（固态硬盘）靠芯片电路直接存取数据。**两者内部结构完全不同，这也决定了它们在随机读取、抗震和寿命方面的表现差异。

![HDD内部盘片与磁头组件](https://thumb.wikimedia.org/wikipedia/commons/thumb/e/ec/Seagate_ST33232A_hard_disk_head_and_platters_detail.jpg/250px-Seagate_ST33232A_hard_disk_head_and_platters_detail.jpg?utm_source=en.wikipedia.org&utm_campaign=parser&utm_content=thumbnail)

**内部结构差异**
- **HDD：**由盘片、主轴电机、磁头臂组件和控制器组成。盘片表面是同心圆轨道，磁头飞行在盘片上方仅约3～5纳米的位置，靠音圈电机在磁道之间移动，通过感应磁性存储单元完成读写（[Wikipedia](https://en.wikipedia.org/wiki/Disk_read-and-write_head)、[Stellar](https://www.stellarinfo.co.in/hdd/key-components-of-hard-drive.php)）。
- **SSD：**由NAND闪存颗粒、主控芯片和DRAM缓存组成，完全没有活动部件。数据写入以“页”为单位，擦除则以更大的“块”为单位，因此必须先擦再写，并且要靠主控进行地址映射、磨损均衡和垃圾回收（[Samsung](https://semiconductor.samsung.com/support/tools-resources/dictionary/semiconductors-101-part-3-inner-workings-of-the-ssd/)、[SSSTC](https://www.ssstc.com/knowledge-detail/how-ssds-work-guide/)）。

![SSD的控制器、NAND与DRAM结构示意](https://media.licdn.com/dms/image/v2/D5612AQE12ZVoQB05HQ/article-cover_image-shrink_720_1280/B56Z1wPWoEGwAM-/0/1775704576626?e=2147483647&v=beta&t=D8N1aEbmCIn3qqAZtsjOya3xcA2gg1AC-ni9On00WcE)

**对三项特性的影响**
1. **随机读取：** HDD每次读取零散数据，都要先等待盘片旋转到正确位置，再移动磁头寻道，因此延迟在毫秒级，随机读写性能远低于顺序读写。SSD通过地址映射直接定位闪存单元，多个闪存通道还能并行读取，所以随机读取延迟在微秒级，基本不受数据位置影响。
2. **抗震：** HDD的磁头依靠空气悬浮，即使轻微振动或跌落，也可能导致磁头撞击盘片、划伤盘片，丢失数据；此外，盘片在灰尘环境下极为脆弱。SSD没有活动部件，抗冲击和振动能力很强。
3. **寿命：** HDD的寿命主要取决于机械磨损和磁头、电机的故障，与写入量关系不大。SSD的寿命则受闪存“擦写次数”限制，写入越多，磨损越快；不过主控的磨损均衡和纠错能大幅延缓衰减，对普通用户而言，闪存磨损通常不是主要问题。

**图片来源：** [Wikipedia：Disk read-and-write head](https://en.wikipedia.org/wiki/Disk_read-and-write_head)；[LinkedIn：SSD Internal Structure Explained](https://www.linkedin.com/pulse/ssd-internal-structure-explained-controller-nand-nlgac)