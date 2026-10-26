# Optional: synthesis + implementation + bitstream from the Tcl console.
# Works on whichever project is currently open (vivado_proj/rv32im.xpr, or the hand-written rv32im.xpr):
#   source build_bitstream.tcl
set script_dir [file dirname [file normalize [info script]]]
reset_run synth_1
launch_runs synth_1 -jobs 4
wait_on_run synth_1
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
open_run impl_1
report_timing_summary -file $script_dir/timing_summary.rpt
report_utilization    -file $script_dir/utilization.rpt
puts "Done. Check $script_dir/timing_summary.rpt: WNS must be >= 0."
puts "Bitstream: [get_property DIRECTORY [current_run]]/soc_top.bit"
