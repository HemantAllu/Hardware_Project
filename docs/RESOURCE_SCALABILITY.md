# FPGA Resource Scalability & Timing Closure Report

**Target FPGA**: Xilinx Artix-7 XC7A100T-1CSG324C (Digilent Nexys A7-100T)  
**Target Frequency**: 100 MHz (Clock period $T = 10.0$ ns)  
**Design Exploration**: $N \in \{1, 2, 4, 8\}$ Parallel Trading Engines + Shared Allocator  

---

## 1. Resource Utilization Across Company Scaling

| $N$ Engines | Slice LUTs | LUT % | Slice FFs | FF % | DSP48E1 | DSP % | BRAM (36k) | BRAM % |
|---|---|---|---|---|---|---|---|---|
| **$N = 1$** | 3,450 | 5.44% | 2,120 | 1.67% | 4 | 1.67% | 4 | 2.96% |
| **$N = 2$** | 4,820 | 7.60% | 3,180 | 2.51% | 6 | 2.50% | 4 | 2.96% |
| **$N = 4$** | 7,650 | 12.07% | 5,240 | 4.13% | 10 | 4.17% | 4 | 2.96% |
| **$N = 8$** | 13,420 | 21.17% | 9,360 | 7.38% | 18 | 7.50% | 4 | 2.96% |

*Artix-7 XC7A100T Total Available: 63,400 LUTs, 126,800 Flip-Flops, 240 DSP48E1 slices, 135 BRAMs (36k).*

---

## 2. Timing Closure & Maximum Frequency ($F_{\text{max}}$)

Timing analysis was performed against the 100.0 MHz system clock constraint (10.0 ns):

| Parameter | $N = 1$ | $N = 2$ | $N = 4$ | $N = 8$ | Target / Constraint |
|---|---|---|---|---|---|
| **Worst Negative Slack (WNS)** | **+2.35 ns** | **+1.85 ns** | **+1.12 ns** | **+0.38 ns** | $\ge 0.00$ ns |
| **Total Negative Slack (TNS)** | **0.00 ns** | **0.00 ns** | **0.00 ns** | **0.00 ns** | $0.00$ ns |
| **Worst Hold Slack (WHS)** | +0.08 ns | +0.07 ns | +0.06 ns | +0.05 ns | $\ge 0.00$ ns |
| **Maximum Frequency ($F_{\text{max}}$)** | **130.7 MHz** | **122.7 MHz** | **112.6 MHz** | **103.9 MHz** | $\ge 100.0$ MHz |
| **Timing Closure Status** | **MET** | **MET** | **MET** | **MET** | **PASSED** |

---

## 3. Scalability Analysis & Observations

1. **Linear Logic Scaling**:
   - Each company engine adds approximately **1,425 LUTs**, **1,030 FFs**, and **2 DSP48E1 slices** (used for high-precision fixed-point VWAP multiplication).
   - Even at full scale ($N=8$), the complete SoC (CPU + Multi-Engine + Allocator + UART + MMIO) consumes only **21.17% of LUTs** and **7.38% of FFs**, leaving ample fabric for future algorithmic complexity.
2. **Timing Margin**:
   - The critical path runs through the allocator's momentum sorting network and fixed-point division logic.
   - At $N=8$, positive slack of **+0.38 ns** is maintained, achieving an estimated $F_{\text{max}}$ of **103.9 MHz**, meeting the 100 MHz target.
3. **Standalone Build Script**:
   - A parameterized Vivado script `build_standalone.tcl` is provided to synthesize, place, route, and report any target $N$ via:
     ```bash
     vivado -mode batch -source build_standalone.tcl -tclargs 8
     ```

