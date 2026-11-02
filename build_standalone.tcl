# -----------------------------------------------------------------------------
# build_standalone.tcl - Reproducible Vivado build system for RV32IM Trading SoC
#
# Usage:
#   vivado -mode batch -source build_standalone.tcl -tclargs <N_COMPANIES> [bitstream]
# Examples:
#   vivado -mode batch -source build_standalone.tcl -tclargs 2
#   vivado -mode batch -source build_standalone.tcl -tclargs 4
#   vivado -mode batch -source build_standalone.tcl -tclargs 8 bitstream
# -----------------------------------------------------------------------------
set script_file [info script]
set root [file dirname [file normalize $script_file]]

# 1. Parse command-line arguments
set n_companies 2
set make_bitstream 1

if {[info exists argv] && [llength $argv] > 0} {
    set n_companies [lindex $argv 0]
    if {[llength $argv] > 1} {
        set opt [lindex $argv 1]
        if {$opt eq "nobit" || $opt eq "0"} {
            set make_bitstream 0
        }
    }
}

puts "=========================================================================="
puts "  BUILDING RV32IM TRADING SOC: HFT_N_MAX = $n_companies"
puts "  Target Part: xc7a100tcsg324-1 (Digilent Nexys A7-100T)"
puts "  Bitstream Generation: [expr {$make_bitstream ? {ENABLED} : {DISABLED}}]"
puts "=========================================================================="

# 2. Source file manifest
set rtl_files {
    alu control dmem forwarding_unit hazard_unit imem imm_gen
    muldiv_unit regfile rv32im_core seg7_driver soc_top
    hft_mmio hft_multi hft_alloc hft_accelerator tick_parser uart
}

# Verify required files
set missing {}
foreach m $rtl_files {
    if {![file exists "$root/src/rtl/$m.v"]} { lappend missing "src/rtl/$m.v" }
}
if {![file exists "$root/src/constraints/nexys_a7_100t.xdc"]} { lappend missing "src/constraints/nexys_a7_100t.xdc" }
if {![file exists "$root/src/mem/imem.mem"]} { lappend missing "src/mem/imem.mem" }
if {![file exists "$root/src/mem/dmem.mem"]} { lappend missing "src/mem/dmem.mem" }

if {[llength $missing] > 0} {
    error "ERROR: Missing required project files: $missing"
}

# 3. Create or reset project
set proj_dir "$root/vivado_proj_N${n_companies}"
catch { close_project }
create_project -force "rv32im_N${n_companies}" $proj_dir -part xc7a100tcsg324-1

# Add RTL sources
set srcs {}
foreach m $rtl_files { lappend srcs "$root/src/rtl/$m.v" }
add_files -norecurse -fileset sources_1 $srcs
add_files -norecurse -fileset sources_1 [list "$root/src/mem/imem.mem" "$root/src/mem/dmem.mem"]
add_files -norecurse -fileset constrs_1 [list "$root/src/constraints/nexys_a7_100t.xdc"]

# Set top-level and explicitly pass generic parameter
set_property top soc_top [get_filesets sources_1]
set_property generic [list HFT_N_MAX=$n_companies] [get_filesets sources_1]

update_compile_order -fileset sources_1

# Create results folder
set res_dir "$root/results"
file mkdir $res_dir

# 4. Run Synthesis
puts "\n[clock format [clock seconds] -format {%T}]: Starting Synthesis..."
reset_run synth_1
launch_runs synth_1 -jobs 4
wait_on_run synth_1

if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {
    error "ERROR: Synthesis failed. Check $proj_dir/rv32im_N${n_companies}.runs/synth_1/runme.log"
}
puts "[clock format [clock seconds] -format {%T}]: Synthesis completed successfully."

# 5. Run Implementation
puts "\n[clock format [clock seconds] -format {%T}]: Starting Implementation..."
reset_run impl_1
if {$make_bitstream} {
    launch_runs impl_1 -to_step write_bitstream -jobs 4
} else {
    launch_runs impl_1 -jobs 4
}
wait_on_run impl_1

if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    error "ERROR: Implementation failed. Check $proj_dir/rv32im_N${n_companies}.runs/impl_1/runme.log"
}
puts "[clock format [clock seconds] -format {%T}]: Implementation completed successfully."

# 6. Generate Reports
open_run impl_1
set timing_rpt "$res_dir/timing_summary_N${n_companies}.rpt"
set util_rpt   "$res_dir/utilization_N${n_companies}.rpt"

report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -file $timing_rpt
report_utilization -file $util_rpt

# Query WNS and TNS
set wns [get_property STATS.WNS [get_runs impl_1]]
set tns [get_property STATS.TNS [get_runs impl_1]]

puts "\n=========================================================================="
puts "  IMPLEMENTATION REPORT SUMMARY (N = $n_companies)"
puts "  Worst Negative Slack (WNS): $wns ns"
puts "  Total Negative Slack (TNS): $tns ns"
if {$wns >= 0.0} {
    puts "  >>> 100 MHz TIMING MET (TIMING CLOSED) <<<"
} else {
    puts "  >>> WARNING: TIMING VIOLATION (WNS < 0) <<<"
}
puts "  Timing Report:      $timing_rpt"
puts "  Utilization Report: $util_rpt"

if {$make_bitstream} {
    set bit_file "$proj_dir/rv32im_N${n_companies}.runs/impl_1/soc_top.bit"
    if {[file exists $bit_file]} {
        file copy -force $bit_file "$res_dir/soc_top_N${n_companies}.bit"
        puts "  Bitstream:          $res_dir/soc_top_N${n_companies}.bit"
    }
}
puts "==========================================================================\n"

