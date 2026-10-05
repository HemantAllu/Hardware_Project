# -----------------------------------------------------------------------------
# create_project.tcl  -  RECOMMENDED way to open this design in Vivado.
#
# Lets Vivado write its own project (./vivado_proj/rv32im.xpr) from the files in ./src,
# so it never depends on a hand-made .xpr.  Nothing is copied: the project points at ./src.
#
#   Vivado GUI:   Tools -> Run Tcl Script... -> pick this file
#   Tcl console:  cd {C:/rv32im_vivado}   then   source create_project.tcl
#   Windows:      double-click open_in_vivado.bat      (starts Vivado and runs this script)
#
# Safe to run again: it replaces ./vivado_proj each time.
# -----------------------------------------------------------------------------
set script_file [info script]
if {$script_file eq ""} {
    error "Run this with 'source create_project.tcl' or Tools -> Run Tcl Script (info script is empty)."
}
set root [file dirname [file normalize $script_file]]

# ---- pre-flight: every file must exist, otherwise explain instead of failing later ----
set rtl_files {
    alu control dmem forwarding_unit hazard_unit imem imm_gen
    muldiv_unit regfile rv32im_core seg7_driver soc_top
    hft_mmio hft_multi hft_alloc hft_accelerator tick_parser uart
}
set need {}
foreach m $rtl_files { lappend need src/rtl/$m.v }
lappend need src/mem/imem.mem src/mem/dmem.mem
lappend need src/constraints/nexys_a7_100t.xdc src/sim/tb_muldiv.v

set missing {}
foreach f $need {
    if {![file exists $root/$f]} { lappend missing $f }
}
if {[llength $missing] > 0} {
    puts "============================================================"
    puts "ERROR: these project files were not found under:"
    puts "       $root"
    foreach f $missing { puts "         $f" }
    puts "Most likely the zip was not fully extracted (opened from inside the zip viewer,"
    puts "or only some files were copied).  Extract the WHOLE zip to a short folder such as"
    puts "C:/rv32im_vivado and run this script again from there."
    puts "============================================================"
    error "missing project files (see list above)"
}
if {[string first " " $root] >= 0} {
    puts "WARNING: the path contains spaces ($root). Vivado usually copes, but if anything"
    puts "         fails, move the folder to something like C:/rv32im_vivado."
}
if {[string length $root] > 80} {
    puts "WARNING: the path is long ([string length $root] chars); Windows may hit its path-length limit."
}

# ---- close a project that is already open (e.g. the one that failed to load) ----
catch { close_project }

# ---- build the project ----
# (add_files takes a Tcl list, so every file argument goes through [list ...] to survive spaces in the path)
set proj_dir $root/vivado_proj
create_project rv32im $proj_dir -part xc7a100tcsg324-1 -force

set srcs {}
foreach m $rtl_files { lappend srcs $root/src/rtl/$m.v }
add_files -norecurse -fileset sources_1 $srcs
add_files -norecurse -fileset sources_1 [list $root/src/mem/imem.mem $root/src/mem/dmem.mem]
add_files -norecurse -fileset constrs_1 [list $root/src/constraints/nexys_a7_100t.xdc]
set_property top soc_top [get_filesets sources_1]

add_files -norecurse -fileset sim_1 [list $root/src/sim/tb_muldiv.v]
set_property top tb_muldiv [get_filesets sim_1]

update_compile_order -fileset sources_1

puts ""
puts "Project created: $proj_dir/rv32im.xpr   (top = soc_top, simulation top = tb_muldiv)"
puts "Next: Run Simulation -> Run Behavioral Simulation, then in the Tcl console: run all"
puts "      (expect: TB_MULDIV PASS).  Then Run Synthesis -> Run Implementation -> Generate Bitstream."
puts "After synthesis, search the log for 'readmem': a warning there means imem.mem/dmem.mem were NOT"
puts "found and the CPU would execute NOPs only."
