"""mutate_port.py - prove that tb_hft_port.v + check_port.py catch allocator bugs.
  run from the project root:  python3 extras/tools/mutate_port.py <work dir with m2.txt / m4.txt> <N>
  (make the stimulus first: python3 extras/tools/check_port.py gen <dir>/m<N>.txt 3 <N> 300)
Each line puts ONE bug into a copy of hft_alloc.v, reruns the test and must print CAUGHT
(with N = 2 a few cannot show: the loss share shift is 0, one company gets the whole share,
and two rotations need more companies).  Exits with status 1 if any bug is MISSED."""
import subprocess,sys
P=sys.argv[1]
src=open('src/rtl/hft_alloc.v').read()
M=[("rank: ties to higher index",
    "beat_r[N*k + kk]  <= (score[k] > score[kk]) || ((score[k] == score[kk]) && (k < kk));",
    "beat_r[N*k + kk]  <= (score[k] > score[kk]) || ((score[k] == score[kk]) && (k > kk));"),
   ("min_hold off by one","(hold[ge] >= min_hold)","(hold[ge] > min_hold)"),
   ("margin >= instead of >","(sdiff > $signed({2'b00, margin}))","(sdiff >= $signed({2'b00, margin}))"),
   ("cap < instead of <=","({15'd0, inv_plus_r} <= c_p)","({15'd0, inv_plus_r} < c_p)"),
   ("cap shift ignored","c_p <= c_m >> c_sh;","c_p <= c_m >> 14;"),
   ("rotation victim may be a buyer","(pos[ge] != 32'd0) && !cand[ge] &&","(pos[ge] != 32'd0) &&"),
   ("rotate twice","end else if (rot_en && !rotated && cap_ok) begin","end else if (rot_en && cap_ok) begin"),
   ("divider stale guard off","if (dv[d_idx]) d_stale <= 1'b1;",""),
   ("floor ignored","take = (wv - t0v < fl) ? ((wv > fl) ? wv - fl : 16'd0) : t0v;","take = t0v;"),
   ("loss share not split","share <= ti >> share_shift(nsym);","share <= ti;"),
   ("max_lots ignored","qty[k]  <= (max_lots == 32'd0 || lvol[k] < max_lots) ? lvol[k] : max_lots;","qty[k]  <= lvol[k];"),
   ("hold no saturation","hold[k] != 8'd255","1'b1"),
   ("score sign lost","score[d_idx] <= d_neg ?","score[d_idx] <= 1'b0 ?"),
   # v12: the one-cycle selection and the parallel reweight
   ("victim: ties to higher index",
    "lbeat_r[N*k + kk] <= (score[k] < score[kk]) || ((score[k] == score[kk]) && (k < kk));",
    "lbeat_r[N*k + kk] <= (score[k] < score[kk]) || ((score[k] == score[kk]) && (k > kk));"),
   ("rank off: reverse order","else         okb = okb && (!avail_v[ja] || (ka < ja));",
    "else         okb = okb && (!avail_v[ja] || (ka > ja));"),
   ("loss: loser pays one share","w[i] <= wi - share * (ns_eff - 4'd1);","w[i] <= wi - share;"),
   ("win: winner not credited","w[i] <= wi + t_sum;","w[i] <= wi;"),
]
missed=0
for name,a,b in M:
    assert src.count(a)==1,(name,src.count(a))
    open(P+'/mut.v','w').write(src.replace(a,b))
    subprocess.run(['iverilog','-g2012','-P','tb_hft_port.N='+sys.argv[2],'-o',P+'/mut.vvp','extras/tb/tb_hft_port.v','src/rtl/hft_multi.v',P+'/mut.v','src/rtl/hft_accelerator.v'],check=True)
    subprocess.run('cd %s && vvp -n mut.vvp +OPS=m%s.txt > ml.txt'%(P,sys.argv[2]),shell=True)
    r=subprocess.run([sys.executable,'extras/tools/check_port.py','check',P+'/ml.txt',sys.argv[2]],capture_output=True,text=True).stdout
    mm=[l for l in r.splitlines() if 'mismatches' in l][0].split('mismatches: ')[1]
    print('%-32s %s'%(name,'CAUGHT ('+mm+' mismatches)' if mm!='0' else 'MISSED'))
    missed += mm=='0'
print('mutations: %d, missed: %d' % (len(M), missed))
sys.exit(1 if missed else 0)
