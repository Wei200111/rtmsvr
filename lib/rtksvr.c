/*------------------------------------------------------------------------------
* rtksvr.c : rtk server functions
*
*          Copyright (C) 2007-2020 by T.TAKASU, All rights reserved.
*
* options : -DWIN32    use WIN32 API
*
* version : $Revision:$ $Date:$
* history : 2009/01/07  1.0  new
*           2009/06/02  1.1  support glonass
*           2010/07/25  1.2  support correction input/log stream
*                            supoort online change of output/log streams
*                            supoort monitor stream
*                            added api:
*                                rtksvropenstr(),rtksvrclosestr()
*                            changed api:
*                                rtksvrstart()
*           2010/08/25  1.3  fix problem of ephemeris time inversion (2.4.0_p6)
*           2010/09/08  1.4  fix problem of ephemeris and ssr squence upset
*                            (2.4.0_p8)
*           2011/01/10  1.5  change api: rtksvrstart(),rtksvrostat()
*           2011/06/21  1.6  fix ephemeris handover problem
*           2012/05/14  1.7  fix bugs
*           2013/03/28  1.8  fix problem on lack of glonass freq number in raw
*                            fix problem on ephemeris with inverted toe
*                            add api rtksvrfree()
*           2014/06/28  1.9  fix probram on ephemeris update of beidou
*           2015/04/29  1.10 fix probram on ssr orbit/clock inconsistency
*           2015/07/31  1.11 add phase bias (fcb) correction
*           2015/12/05  1.12 support opt->pppopt=-DIS_FCB
*           2016/07/01  1.13 support averaging single pos as base position
*           2016/07/31  1.14 fix bug on ion/utc parameters input
*           2016/08/20  1.15 support api change of sendnmea()
*           2016/09/18  1.16 fix server-crash with server-cycle > 1000
*           2016/09/20  1.17 change api rtksvrstart()
*           2016/10/01  1.18 change api rtksvrstart()
*           2016/10/04  1.19 fix problem to send nmea of single solution
*           2016/10/09  1.20 add reset-and-single-sol mode for nmea-request
*           2017/04/11  1.21 add rtkfree() in rtksvrfree()
*           2020/11/30  1.22 add initializing svr->nav in rtksvrinit()
*                            allocate double size ephemeris in rtksvrinit()
*                            handle multiple ephemeris sets in updatesvr()
*                            use API sat2freq() to get carrier frequency
*                            use integer types in stdint.h
*-----------------------------------------------------------------------------*/
#include "rtklib.h"
// #include "ism_cal.h"
#include "ism.h"

#define MIN_INT_RESET   30000   /* mininum interval of reset command (ms) */

/* initialize RTK control ------------------------------------------------------
* initialize RTK control struct
* args   : rtk_t    *rtk    IO  TKk control/result struct
*          prcopt_t *opt    I   positioning options (see rtklib.h)
* return : none
*-----------------------------------------------------------------------------*/
extern void rtkinit(rtk_t *rtk, const prcopt_t *opt)
{
    sol_t sol0={{0}};
    ambc_t ambc0={{{0}}};
    ssat_t ssat0={0};
    int i;

    trace(3,"rtkinit: start initialization\n");

    rtk->sol=sol0;
    for (i=0;i<6;i++) rtk->rb[i]=0.0;
    // rtk->nx=opt->mode<=PMODE_FIXED?NX(opt):pppnx(opt);  /* 缺少NX宏定义 */
    // rtk->na=opt->mode<=PMODE_FIXED?NR(opt):pppnx(opt);  /* 缺少NR宏定义 */
    rtk->nx = 0; 
    rtk->na = 0;  
    trace(4,"rtkinit: nx=%d na=%d\n", rtk->nx, rtk->na);
    rtk->tt=0.0;
    rtk->epoch=0;
    if (rtk->nx > 0) {
        rtk->x=zeros(rtk->nx,1);
        rtk->P=zeros(rtk->nx,rtk->nx);
        if (!rtk->x || !rtk->P) {
            trace(1,"rtkinit: memory allocation failed for state vectors nx=%d\n", rtk->nx);
            // 清理已分配的内存
            if (rtk->x) { free(rtk->x); rtk->x = NULL; }
            if (rtk->P) { free(rtk->P); rtk->P = NULL; }
            return;  // void函数直接返回
        }
    } else {
        rtk->x = NULL;
        rtk->P = NULL;
    }
    if (rtk->na > 0) {
        rtk->xa=zeros(rtk->na,1);
        rtk->Pa=zeros(rtk->na,rtk->na);
        if (!rtk->xa || !rtk->Pa) {
            trace(1,"rtkinit: memory allocation failed for ambiguity vectors na=%d\n", rtk->na);
            // 清理已分配的内存
            if (rtk->x) { free(rtk->x); rtk->x = NULL; }
            if (rtk->P) { free(rtk->P); rtk->P = NULL; }
            if (rtk->xa) { free(rtk->xa); rtk->xa = NULL; }
            if (rtk->Pa) { free(rtk->Pa); rtk->Pa = NULL; }
            return;  // void函数直接返回
        }
    } else {
        rtk->xa = NULL;
        rtk->Pa = NULL;
    }
    rtk->nfix=rtk->neb=0;
    for (i=0;i<MAXSAT;i++) {
        rtk->ambc[i]=ambc0;
        rtk->ssat[i]=ssat0;
    }
    rtk->holdamb=0;
    rtk->excsat=0;
    rtk->nb_ar=0;
    for (i=0;i<MAXERRMSG;i++) rtk->errbuf[i]=0;
    rtk->opt=*opt;
    rtk->initial_mode=rtk->opt.mode;
    rtk->sol.thres=(float)opt->thresar[0];
}
/* free rtk control ------------------------------------------------------------
* free memory for rtk control struct
* args   : rtk_t    *rtk    IO  rtk control/result struct
* return : none
*-----------------------------------------------------------------------------*/
extern void rtkfree(rtk_t *rtk)
{
    trace(3,"rtkfree: start freeing RTK control struct\n");

    rtk->nx=rtk->na=0;
    if (rtk->x) { free(rtk->x); rtk->x=NULL; }
    if (rtk->P) { free(rtk->P); rtk->P=NULL; }
    if (rtk->xa) { free(rtk->xa); rtk->xa=NULL; }
    if (rtk->Pa) { free(rtk->Pa); rtk->Pa=NULL; }
    
    trace(4,"rtkfree: RTK control struct freed successfully\n");
}

/* 函数声明 ----------------------------------------------------------------*/
static int input_meas(scintillation_calculator_t *scint_calc);
static void cleanup_rtk_server_resources(rtksvr_t *svr);
static int process_stream_data(rtksvr_t *svr, int stream_idx, int *bytes_read);
static int decode_stream_frames(rtksvr_t *svr, int stream_idx, scintillation_calculator_t *scint_calc);
static int should_calculate_ism(scintillation_calculator_t *scint_calc, uint32_t tick, uint32_t tickscint);
static int process_ism_calculation(rtksvr_t *svr, scintillation_calculator_t *scint_calc, int *n_scint_uint);

/* write solution header to output stream ------------------------------------*/
static void writesolhead(stream_t *stream, const solopt_t *solopt)
{
    uint8_t buff[1024];
    int n = 0; /* avoid writing uninitialized memory if header encoder is disabled */
    
    // n=outsolheads(buff,solopt);
    strwrite(stream,buff,n);
}
/* save output buffer --------------------------------------------------------*/
static void saveoutbuf(rtksvr_t *svr, uint8_t *buff, int n, int index)
{
    rtksvrlock(svr);
    
    n=n<svr->buffsize-svr->nsb[index]?n:svr->buffsize-svr->nsb[index];
    memcpy(svr->sbuf[index]+svr->nsb[index],buff,n);
    svr->nsb[index]+=n;
    
    rtksvrunlock(svr);
}
/* write solution to output stream -------------------------------------------*/
static void writesol(rtksvr_t *svr, int index)
{
    solopt_t solopt=solopt_default;
    uint8_t buff[MAXSOLMSG+1];
    int i,n=0;
    
    tracet(4,"writesol: index=%d\n",index);
    
    for (i=0;i<2;i++) {
        
        if (svr->solopt[i].posf==SOLF_STAT) {
            
            // /* output solution status */
            // rtksvrlock(svr);
            // n=rtkoutstat(&svr->rtk,(char *)buff);
            // rtksvrunlock(svr);
        }
        else {
            /* output solution */
            // n=outsols(buff,&svr->rtk.sol,svr->rtk.rb,svr->solopt+i);
        }
        if (n>0) strwrite(svr->stream+i+3,buff,n);
        
        /* save output buffer */
        if (n>0) saveoutbuf(svr,buff,n,i);
        
        /* output extended solution */
        // n=outsolexs(buff,&svr->rtk.sol,svr->rtk.ssat,svr->solopt+i);
        if (n>0) strwrite(svr->stream+i+3,buff,n);
        
        /* save output buffer */
        if (n>0) saveoutbuf(svr,buff,n,i);
    }
    /* output solution to monitor port */
    if (svr->moni) {
        // n=outsols(buff,&svr->rtk.sol,svr->rtk.rb,&solopt);
        if (n>0) strwrite(svr->moni,buff,n);
    }
    /* save solution buffer */
    if (svr->nsol<MAXSOLBUF) {
        rtksvrlock(svr);
        svr->solbuf[svr->nsol++]=svr->rtk.sol;
        rtksvrunlock(svr);
    }
}
/* periodic command ----------------------------------------------------------*/
static void periodic_cmd(int cycle, const char *cmd, stream_t *stream)
{
    const char *p=cmd,*q;
    char msg[1024],*r;
    int n,period;
    
    trace(4,"periodic_cmd: cycle=%d\n", cycle);
    
    for (p=cmd;;p=q+1) {
        for (q=p;;q++) if (*q=='\r'||*q=='\n'||*q=='\0') break;
        n=(int)(q-p); strncpy(msg,p,n); msg[n]='\0';
        
        period=0;
        if ((r=strrchr(msg,'#'))) {
            sscanf(r,"# %d",&period);
            *r='\0';
            while (*--r==' ') *r='\0'; /* delete tail spaces */
        }
        if (period<=0) period=1000;
        if (*msg&&cycle%period==0) {
            strsendcmd(stream,msg);
            trace(4,"periodic_cmd: sent command: %s\n", msg);
        }
        if (!*q) break;
    }
}

/* 数据流读取和处理 ---------------------------------------------------------*/
static int process_stream_data(rtksvr_t *svr, int stream_idx, int *bytes_read)
{
    uint8_t *p, *q;
    int n;
    
    if (stream_idx < 0 || stream_idx >= 3) return 0;
    
    p = svr->buff[stream_idx] + svr->nb[stream_idx];
    q = svr->buff[stream_idx] + svr->buffsize;
    
    /* 若到达缓冲区末尾，则从头开始复用（避免“缓冲区满”后永久停读） */
    if (p >= q) {
        trace(4,"process_stream_data: wrapping buffer for stream[%d]\n", stream_idx);
        svr->nb[stream_idx] = 0;
        p = svr->buff[stream_idx];
        q = svr->buff[stream_idx] + svr->buffsize;
    }
    
    /* 再次检查（极端情况下 buffsize==0） */
    if (p >= q) {
        trace(2,"process_stream_data: buffer full or invalid size for stream[%d]\n", stream_idx);
        return 0;
    }
    
    /* 从输入流读取数据 */
    n = strread(svr->stream + stream_idx, p, q - p);
    if (n <= 0) return 0;
    
    *bytes_read += n;
    trace(5,"process_stream_data: stream[%d] read %d bytes\n", stream_idx, n);
    
    /* 写入日志流 */
    strwrite(svr->stream + stream_idx + 5, p, n);
    /* 这里的 buff 仅作临时读写与日志用途，不需要长期累积，读写一次即复位起点 */
    svr->nb[stream_idx] = 0;
    
    /* 更新peek缓冲区 */
    rtksvrlock(svr);
    int copy_size = (n < svr->buffsize - svr->npb[stream_idx]) ? 
                    n : svr->buffsize - svr->npb[stream_idx];
    if (copy_size > 0) {
        memcpy(svr->pbuf[stream_idx] + svr->npb[stream_idx], p, copy_size);
        svr->npb[stream_idx] += copy_size;
    }
    rtksvrunlock(svr);
    
    return n;
}

/* 解码数据帧 ---------------------------------------------------------------*/
static int decode_stream_frames(rtksvr_t *svr, int stream_idx, scintillation_calculator_t *scint_calc)
{
    int decoded_frames = 0;
    
    if (stream_idx < 0 || stream_idx >= 3 || svr->npb[stream_idx] == 0) {
        return 0;
    }
    
    trace(4,"decode_stream_frames: decoding stream[%d] with %d bytes buffered\n", 
          stream_idx, svr->npb[stream_idx]);
    
    decode_monitor_raw(svr, stream_idx);
    
    monitor_decoder_t *decoder = (monitor_decoder_t*)svr->rtcm[stream_idx].monitor_decoder;
    if (!decoder) return 0;
    
    decoded_frames = decoder->valid_frames;
    
    if (decoded_frames > 0) {
        trace(3,"decode_stream_frames: stream[%d] decoded %d valid frames\n", 
              stream_idx, decoded_frames);
        
        measlog(svr, stream_idx);
        
        /* 输入数据到闪烁计算器 */
        if (scint_calc && scint_calc->ismopt.calculate) {
            int input_count = input_meas(scint_calc);
            trace(3,"decode_stream_frames: input %d measurement items to scint calculator\n", input_count);
        }
        
        init_data_buffer();

        /* 解码成功后显式复位 peek 缓冲累计字节，防止 npb 长期增长导致后续复制停止 */
        rtksvrlock(svr);
        svr->npb[stream_idx] = 0;
        rtksvrunlock(svr);
        trace(5, "decode_stream_frames: reset peek buffer npb for stream[%d]\n", stream_idx);
    } else {
        trace(4,"decode_stream_frames: stream[%d] no valid frames decoded\n", stream_idx);
    }
    
    return decoded_frames;
}

/* 输入测量数据到闪烁计算器 -------------------------------------------------*/
static int input_meas(scintillation_calculator_t *scint_calc)
{
    int i, total_input = 0;

    if (!scint_calc) return 0;

    trace(3,"input_meas: start inputting buffered data to scint calculator\n");
    trace(2,"input_meas: buffer stats - gnss_meas:%d gnss_pos:%d leo_pos:%d corr:%d phase:%d\n", 
          n_gnss_meas_buf, n_gnss_pos_buf, n_leo_pos_buf, n_corr_data_buf, n_phase_data_buf);

    /* 批量处理GNSS测量数据 */
    for (i = 0; i < n_gnss_meas_buf; i++) {
        if (gnss_meas_buf[i].nsat > 0) {
            input_gnss_meas(scint_calc, &gnss_meas_buf[i]);
            total_input++;
            trace(3,"input_meas: input gnss_meas[%d] with %d satellites\n", i, gnss_meas_buf[i].nsat);
        }
    }
    
    /* 批量处理GNSS位置数据 */
    for (i = 0; i < n_gnss_pos_buf; i++) {
        if (gnss_pos_buf[i].nsat > 0) {
            input_gnss_pos_data(scint_calc, &gnss_pos_buf[i]);
            total_input++;
            trace(3,"input_meas: input gnss_pos[%d] with %d satellites\n", i, gnss_pos_buf[i].nsat);
        }
    }

    /* 批量处理LEO位置数据 */
    for (i = 0; i < n_leo_pos_buf; i++) {
        if (leo_pos_buf[i].nsat > 0) {
            input_leo_position_data(scint_calc, &leo_pos_buf[i]);
            total_input++;
            trace(3,"input_meas: input leo_pos[%d] with %d satellites\n", i, leo_pos_buf[i].nsat);
        }
    }
    
    /* 批量处理相关数据 */
    for (i = 0; i < n_corr_data_buf; i++) {
        if (corr_data_buf[i].valid_count > 0) {
            input_iq_correlation_data(scint_calc, &corr_data_buf[i]);
            total_input++;
            trace(3,"input_meas: input corr_data[%d] with %d valid samples\n", i, corr_data_buf[i].valid_count);
        }
    }
    
    /* 批量处理相位数据 */
    for (i = 0; i < n_phase_data_buf; i++) {
        if (phase_data_buf[i].valid_count > 0) {
            input_phase_data(scint_calc, &phase_data_buf[i]);
            total_input++;
            trace(3,"input_meas: input phase_data[%d] with %d valid samples\n", i, phase_data_buf[i].valid_count);
        }
    }
    
    trace(2,"input_meas: finished inputting %d data items to scint calculator\n", total_input);
    return total_input;
}

/* 判断是否需要进行ISM计算 --------------------------------------------------*/
static int should_calculate_ism(scintillation_calculator_t *scint_calc, uint32_t tick, uint32_t tickscint)
{
    if (!scint_calc || !scint_calc->ismopt.calculate) {
        return 0;
    }
    
    /* 基于时间戳触发 */
    if (scint_calc->ismopt.unitdiv == ISMTDOPT_TS && scint_calc->need_cal) {
        trace(3,"should_calculate_ism: ISM calculation triggered by timestamp\n");
        return 1;
    }
    
    /* 基于系统时间触发 */
    if (scint_calc->ismopt.unitdiv == ISMTDOPT_SYS && 
        (int)(tick - tickscint) >= scint_calc->ismopt.windowsize * 1000) {
        trace(3,"should_calculate_ism: ISM calculation triggered by system time, window=%.1fs\n", 
              scint_calc->ismopt.windowsize);
        return 1;
    }
    
    return 0;
}

/* 处理ISM计算和输出 --------------------------------------------------------*/
static int process_ism_calculation(rtksvr_t *svr, scintillation_calculator_t *scint_calc, int *n_scint_uint)
{
    uint8_t sol_buff[4096];
    char ts_str[30] = {0}, te_str[30] = {0};
    int i, j, ns, process_result;
    
    trace(2,"process_ism_calculation: starting ISM calculation unit=%d\n", *n_scint_uint);
    
    process_result = process_scintillation_data(scint_calc);
    
    if (process_result) {
        time2str(scint_calc->start_time, ts_str, 0);
        time2str(scint_calc->last_time, te_str, 0);
        tracet(2, "ISM param calculate finished, n = %d, n_sat = %d, ts = %s te = %s \n",
               *n_scint_uint, scint_calc->n_sat_ism_param, ts_str, te_str);
        
        trace(2,"process_ism_calculation: ISM calculation success - %d satellites processed\n", 
              scint_calc->n_sat_ism_param);
        
        /* 批量输出电离层闪烁参数计算结果 */
        for (i = 0; i < scint_calc->n_sat_ism_param; i++) {
            ns = 0;
            memset(sol_buff, 0, sizeof(sol_buff));
            out_ism_sat(&scint_calc->sat_ism_param[i], sol_buff, &ns);
            
            /* 写入结果数据流 */
            for (j = 0; j < 2; j++) {
                strwrite(svr->stream + j + 3, sol_buff, ns / 8);
            }
            
            /* 写入ISM日志 */
            if (scint_calc->ismopt.ismlog) {
                ismoutsat(&scint_calc->sat_ism_param[i]);
            }
            
            trace(3,"process_ism_calculation: output ISM params for satellite[%d]\n", i);
        }

        (*n_scint_uint)++;
        
        /* 重置闪烁计算器为下一计算周期 */
        free_scintillation_calculator(scint_calc);
        if (init_scintillation_calculator(scint_calc, &svr->ismopt) != 0) {
            trace(1,"process_ism_calculation: failed to reinitialize scint calculator\n");
        }
        svr->last_scint_output = scint_calc->last_time;
        trace(3,"process_ism_calculation: ISM calculator reset for next calculation period\n");
        
        return 1;
    } else {
        tracet(2, "闪烁参数处理失败: %d\n", process_result);
        trace(2,"process_ism_calculation: ISM calculation failed with result=%d\n", process_result);
        return 0;
    }
}

/* RTK服务器线程 ------------------------------------------------------------*/
static void *rtksvrthread(void *arg)
{
    rtksvr_t *svr = (rtksvr_t *)arg;
    scintillation_calculator_t *scint_calc = (scintillation_calculator_t *)svr->scint_calc;
    
    /* 时间戳变量 */
    uint32_t tick, ticknmea, tick1hz, tickreset, tickscint;
    
    /* 计数器和状态变量 */
    int cycle = 0, cputime = 0, n_scint_uint = 1;
    int i, total_bytes_read, total_frames, nframe[3] = {0};
    
    trace(3,"rtksvrthread: start RTK server thread\n");
    tracet(3,"rtksvrthread: thread starting\n");
    
    /* 初始化时间戳 */
    svr->state = 1;
    svr->tick = tickget();
    ticknmea = tick1hz = svr->tick - 1000;
    tickreset = svr->tick - MIN_INT_RESET;
    tickscint = svr->tick - 1000;

    /* 验证闪烁计算器初始化状态 */
    if (!scint_calc) {
        trace(1,"rtksvrthread: scintillation calculator not initialized\n");
    } else {
        trace(2,"rtksvrthread: scintillation calculator initialized, calculate=%d\n", 
              scint_calc->ismopt.calculate);
    }

    /* 主处理循环 */
    for (cycle = 0; svr->state; cycle++) {
        tick = tickget();
        
        /* 周期性性能统计 */
        if (cycle % 1000 == 0 && cycle > 0) {
            trace(4,"rtksvrthread: cycle=%d, running for %.1f seconds\n", 
                  cycle, (tick - svr->tick) / 1000.0);
        }

        /* 阶段1: 数据流读取 */
        total_bytes_read = 0;
        for (i = 0; i < 3; i++) {
            int bytes_read = 0;
            if (process_stream_data(svr, i, &bytes_read) > 0) {
                total_bytes_read += bytes_read;
            }
        }
        
        if (total_bytes_read > 0) {
            trace(2,"rtksvrthread: cycle=%d total bytes read=%d\n", cycle, total_bytes_read);
        }
        
        /* 阶段2: 数据解码和处理 */
        total_frames = 0;
        for (i = 0; i < 3; i++) {
            nframe[i] = decode_stream_frames(svr, i, scint_calc);
            total_frames += nframe[i];
        }
        
        if (total_frames > 0) {
            trace(2,"rtksvrthread: cycle=%d decoded total frames=%d [%d,%d,%d]\n", 
                  cycle, total_frames, nframe[0], nframe[1], nframe[2]);
        }

        /* 阶段3: ISM计算判断和处理 */
        if (should_calculate_ism(scint_calc, tick, tickscint)) {
            if (process_ism_calculation(svr, scint_calc, &n_scint_uint)) {
                /* ISM计算成功，更新时间戳 */
                if (scint_calc->ismopt.unitdiv == ISMTDOPT_SYS) {
                    tickscint = tick;
                }
            }
        }

        /* 阶段4: 性能监控和周期控制 */
        cputime = (int)(tickget() - tick);
        if (cputime > 0) {
            svr->cputime = cputime;
            if (cputime > svr->cycle) {
                trace(2,"rtksvrthread: cycle overrun - cputime=%dms > cycle=%dms\n", 
                      cputime, svr->cycle);
            }
        }
        
        /* 休眠到下一个周期 */
        int sleep_time = svr->cycle - cputime;
        if (sleep_time > 0) {
            sleepms(sleep_time);
        }
        
    } /* end of rtksvrthread main loop */
    
    trace(2,"rtksvrthread: thread terminating after %d cycles\n", cycle);
    
    /* 资源清理阶段 */
    cleanup_rtk_server_resources(svr);
    
    return 0;
}

/* 清理RTK服务器资源 --------------------------------------------------------*/
static void cleanup_rtk_server_resources(rtksvr_t *svr)
{
    int i;
    
    trace(3,"cleanup_rtk_server_resources: starting resource cleanup\n");
    
    /* 关闭所有数据流 */
    for (i = 0; i < MAXSTRRTK; i++) {
        strclose(svr->stream + i);
    }
    
    /* 清理输入缓冲区和监测解码器 */
    for (i = 0; i < 3; i++) {
        svr->nb[i] = svr->npb[i] = 0;
        
        if (svr->buff[i]) { 
            free(svr->buff[i]); 
            svr->buff[i] = NULL; 
        }
        
        if (svr->pbuf[i]) { 
            free(svr->pbuf[i]); 
            svr->pbuf[i] = NULL; 
        }
        
        /* 清理监测接收机解码器 */
        if (svr->rtcm[i].monitor_decoder) {
            free(svr->rtcm[i].monitor_decoder);
            svr->rtcm[i].monitor_decoder = NULL;
            trace(4,"cleanup_rtk_server_resources: freed monitor decoder for stream[%d]\n", i);
        }
    }
    
    /* 清理闪烁计算器 */
    if (svr->scint_calc) {
        scintillation_calculator_t *scint_calc = (scintillation_calculator_t*)svr->scint_calc;
        free_scintillation_calculator(scint_calc);
        free(svr->scint_calc);
        svr->scint_calc = NULL;
        trace(3,"cleanup_rtk_server_resources: freed scintillation calculator\n");
    }
    
    /* 关闭闪烁日志文件 */
    if (svr->scint_log_file) {
        fclose(svr->scint_log_file);
        svr->scint_log_file = NULL;
        trace(3,"cleanup_rtk_server_resources: closed scintillation log file\n");
    }
    
    /* 清理输出缓冲区 */
    for (i = 0; i < 2; i++) {
        svr->nsb[i] = 0;
        if (svr->sbuf[i]) {
            free(svr->sbuf[i]); 
            svr->sbuf[i] = NULL;
        }
    }
    
    trace(2,"cleanup_rtk_server_resources: resource cleanup completed\n");
}

/* initialize rtk server -------------------------------------------------------
* initialize rtk server
* args   : rtksvr_t *svr    IO rtk server
* return : status (0:error,1:ok)
*-----------------------------------------------------------------------------*/
extern int rtksvrinit(rtksvr_t *svr)
{
    gtime_t time0={0};
    sol_t  sol0 ={{0}};
    eph_t  eph0 ={0,-1,-1};
    geph_t geph0={0,-1};
    seph_t seph0={0};
    int i,j;
    
    trace(3,"rtksvrinit: start initializing RTK server\n");
    
    svr->state=svr->cycle=svr->nmeacycle=svr->nmeareq=0;
    for (i=0;i<3;i++) svr->nmeapos[i]=0.0;
    svr->buffsize=0;
    for (i=0;i<3;i++) svr->format[i]=0;
    for (i=0;i<2;i++) svr->solopt[i]=solopt_default;
    svr->navsel=svr->nsbs=svr->nsol=0;
    rtkinit(&svr->rtk,&prcopt_default);
    for (i=0;i<3;i++) svr->nb[i]=0;
    for (i=0;i<2;i++) svr->nsb[i]=0;
    for (i=0;i<3;i++) svr->npb[i]=0;
    for (i=0;i<3;i++) svr->buff[i]=NULL;
    for (i=0;i<2;i++) svr->sbuf[i]=NULL;
    for (i=0;i<3;i++) svr->pbuf[i]=NULL;
    for (i=0;i<MAXSOLBUF;i++) svr->solbuf[i]=sol0;
    for (i=0;i<3;i++) for (j=0;j<10;j++) svr->nmsg[i][j]=0;
    for (i=0;i<3;i++) svr->ftime[i]=time0;
    for (i=0;i<3;i++) svr->files[i][0]='\0';
    svr->moni=NULL;
    svr->tick=0;
    svr->thread=0;
    svr->cputime=svr->prcout=svr->nave=0;
    for (i=0;i<3;i++) svr->rb_ave[i]=0.0;
    svr->ismopt = ismopt_default;

    memset(&svr->nav,0,sizeof(nav_t));
    if (!(svr->nav.eph =(eph_t  *)malloc(sizeof(eph_t )*MAXSAT*4 ))||
        !(svr->nav.geph=(geph_t *)malloc(sizeof(geph_t)*NSATGLO*2))||
        !(svr->nav.seph=(seph_t *)malloc(sizeof(seph_t)*NSATSBS*2))) {
        trace(1,"rtksvrinit: navigation data malloc error - eph:%p geph:%p seph:%p\n", 
              svr->nav.eph, svr->nav.geph, svr->nav.seph);
        return 0;
    }
    trace(4,"rtksvrinit: allocated navigation data - eph:%d geph:%d seph:%d\n", 
          MAXSAT*4, NSATGLO*2, NSATSBS*2);
    
    for (i=0;i<MAXSAT*4 ;i++) svr->nav.eph [i]=eph0;
    for (i=0;i<NSATGLO*2;i++) svr->nav.geph[i]=geph0;
    for (i=0;i<NSATSBS*2;i++) svr->nav.seph[i]=seph0;
    svr->nav.n =MAXSAT *2;
    svr->nav.ng=NSATGLO*2;
    svr->nav.ns=NSATSBS*2;
    
    for (i=0;i<3;i++) for (j=0;j<MAXOBSBUF;j++) {
        if (!(svr->obs[i][j].data=(obsd_t *)malloc(sizeof(obsd_t)*MAXOBS))) {
            trace(1,"rtksvrinit: observation data malloc error - stream[%d] buffer[%d]\n", i, j);
            return 0;
        }
    }
    trace(4,"rtksvrinit: allocated observation buffers - %d streams x %d buffers x %d obs\n", 
          3, MAXOBSBUF, MAXOBS);
    
    for (i=0;i<3;i++) {
        memset(svr->raw +i,0,sizeof(raw_t ));
        memset(svr->rtcm+i,0,sizeof(rtcm_t));
    }
    for (i=0;i<MAXSTRRTK;i++) strinit(svr->stream+i);
    
    for (i=0;i<3;i++) *svr->cmds_periodic[i]='\0';
    *svr->cmd_reset='\0';
    svr->bl_reset=10.0;
    rtklib_initlock(&svr->lock);

    /* 先释放可能已存在的闪烁计算器 */
    if (svr->scint_calc) {
        free_scintillation_calculator((scintillation_calculator_t*)svr->scint_calc);
        free(svr->scint_calc);
        svr->scint_calc = NULL;
        trace(4,"rtksvrinit: freed existing scintillation calculator\n");
    }

    svr->scint_calc = malloc(sizeof(scintillation_calculator_t));
    if (!svr->scint_calc) {
        trace(2,"rtksvrinit: scintillation calculator malloc failed\n");
        return 0;
    }
    
    if (init_scintillation_calculator((scintillation_calculator_t*)svr->scint_calc,&svr->ismopt) != 0) {
        free(svr->scint_calc);
        svr->scint_calc = NULL;
        trace(2,"rtksvrinit: scintillation calculator init failed\n");
        return 0;
    }
    
    trace(3,"rtksvrinit: scintillation calculator initialized successfully\n");
    
    /* 设置输出参数 */
    svr->scint_output_interval = 60; /* 每60秒输出一次 */
    
    trace(2,"rtksvrinit: RTK server initialization completed successfully\n");
    return 1;
}
/* free rtk server -------------------------------------------------------------
* free rtk server
* args   : rtksvr_t *svr    IO rtk server
* return : none
*-----------------------------------------------------------------------------*/
extern void rtksvrfree(rtksvr_t *svr)
{
    int i,j;
    
    free(svr->nav.eph );
    free(svr->nav.geph);
    free(svr->nav.seph);
    for (i=0;i<3;i++) for (j=0;j<MAXOBSBUF;j++) {
        free(svr->obs[i][j].data);
    }
    rtkfree(&svr->rtk);
}
/* lock/unlock rtk server ------------------------------------------------------
* lock/unlock rtk server
* args   : rtksvr_t *svr    IO rtk server
* return : status (1:ok 0:error)
*-----------------------------------------------------------------------------*/
extern void rtksvrlock  (rtksvr_t *svr) {rtklib_lock  (&svr->lock);}
extern void rtksvrunlock(rtksvr_t *svr) {rtklib_unlock(&svr->lock);}

/* start rtk server ------------------------------------------------------------
* start rtk server thread
* args   : rtksvr_t *svr    IO rtk server
*          int     cycle    I  server cycle (ms)
*          int     buffsize I  input buffer size (bytes)
*          int     *strs    I  stream types (STR_???)
*                              types[0]=input stream rover
*                              types[1]=input stream base station
*                              types[2]=input stream correction
*                              types[3]=output stream solution 1
*                              types[4]=output stream solution 2
*                              types[5]=log stream rover
*                              types[6]=log stream base station
*                              types[7]=log stream correction
*          char    *paths   I  input stream paths
*          int     *format  I  input stream formats (STRFMT_???)
*                              format[0]=input stream rover
*                              format[1]=input stream base station
*                              format[2]=input stream correction
*          int     navsel   I  navigation message select
*                              (0:rover,1:base,2:ephem,3:all)
*          char    **cmds   I  input stream start commands
*                              cmds[0]=input stream rover (NULL: no command)
*                              cmds[1]=input stream base (NULL: no command)
*                              cmds[2]=input stream corr (NULL: no command)
*          char    **cmds_periodic I input stream periodic commands
*                              cmds[0]=input stream rover (NULL: no command)
*                              cmds[1]=input stream base (NULL: no command)
*                              cmds[2]=input stream corr (NULL: no command)
*          char    **rcvopts I receiver options
*                              rcvopt[0]=receiver option rover
*                              rcvopt[1]=receiver option base
*                              rcvopt[2]=receiver option corr
*          int     nmeacycle I nmea request cycle (ms) (0:no request)
*          int     nmeareq  I  nmea request type
*                              (0:no,1:base pos,2:single sol,3:reset and single)
*          double *nmeapos  I  transmitted nmea position (ecef) (m)
*          prcopt_t *prcopt I  rtk processing options
*          solopt_t *solopt I  solution options
*                              solopt[0]=solution 1 options
*                              solopt[1]=solution 2 options
*          stream_t *moni   I  monitor stream (NULL: not used)
*          char   *errmsg   O  error message
* return : status (1:ok 0:error)
*-----------------------------------------------------------------------------*/

extern int rtksvrstart(rtksvr_t *svr, int cycle, int buffsize, int *strs,
                       char **paths, int *formats, int navsel, char **cmds,
                       char **cmds_periodic, char **rcvopts, int nmeacycle,
                       int nmeareq, const double *nmeapos, prcopt_t *prcopt,
                       solopt_t *solopt, stream_t *moni, char *errmsg, ismopt_t *ismopt)
{
    gtime_t time,time0={0};
    int i,j,rw;
    
    trace(3,"rtksvrstart: start RTK server - cycle=%dms buffsize=%d navsel=%d\n",
          cycle, buffsize, navsel);
    
    if (svr->state) {
        sprintf(errmsg,"server already started");
        trace(2,"rtksvrstart: server already running, state=%d\n", svr->state);
        return 0;
    }

    strinitcom();
    svr->cycle=cycle>1?cycle:1;
    svr->nmeacycle=nmeacycle>1000?nmeacycle:1000;
    svr->nmeareq=nmeareq;
    for (i=0;i<3;i++) svr->nmeapos[i]=nmeapos[i];
    svr->buffsize=buffsize>4096?buffsize:4096;
    for (i=0;i<3;i++) svr->format[i]=formats[i];
    svr->navsel=navsel;
    
    trace(4,"rtksvrstart: configured - cycle=%dms buffsize=%d formats=[%d,%d,%d]\n",
          svr->cycle, svr->buffsize, formats[0], formats[1], formats[2]);
    svr->nsbs=0;
    svr->nsol=0;
    svr->prcout=0;
    rtkfree(&svr->rtk);
    rtkinit(&svr->rtk,prcopt);
    svr->ismopt = *ismopt;

    if (prcopt->initrst) { /* init averaging pos by restart */
        svr->nave=0;
        for (i=0;i<3;i++) svr->rb_ave[i]=0.0;
    }
    for (i=0;i<3;i++) { /* input/log streams */
        svr->nb[i]=svr->npb[i]=0;
        if (!(svr->buff[i]=(uint8_t *)malloc(buffsize))||
            !(svr->pbuf[i]=(uint8_t *)malloc(buffsize))) {
            tracet(1,"rtksvrstart: malloc error for stream %d\n", i);
            // 清理已分配的缓冲区
            for (int j = 0; j <= i; j++) {
                if (svr->buff[j]) { free(svr->buff[j]); svr->buff[j] = NULL; }
                if (svr->pbuf[j]) { free(svr->pbuf[j]); svr->pbuf[j] = NULL; }
            }
            sprintf(errmsg,"rtk server malloc error");
            return 0;
        }
        for (j=0;j<10;j++) svr->nmsg[i][j]=0;
        for (j=0;j<MAXOBSBUF;j++) svr->obs[i][j].n=0;
        strcpy(svr->cmds_periodic[i],!cmds_periodic[i]?"":cmds_periodic[i]);
        
        /* set receiver and rtcm option */
        strcpy(svr->raw [i].opt,rcvopts[i]);
        strcpy(svr->rtcm[i].opt,rcvopts[i]);
        
        /* connect dgps corrections */
        svr->rtcm[i].dgps=svr->nav.dgps;
    }
    for (i=0;i<2;i++) { /* output peek buffer */
        if (!(svr->sbuf[i]=(uint8_t *)malloc(buffsize))) {
            tracet(1,"rtksvrstart: malloc error for output buffer %d\n", i);
            // 清理已分配的缓冲区
            for (int j = 0; j < i; j++) {
                if (svr->sbuf[j]) { free(svr->sbuf[j]); svr->sbuf[j] = NULL; }
            }
            // 清理之前分配的输入缓冲区
            for (int j = 0; j < 3; j++) {
                if (svr->buff[j]) { free(svr->buff[j]); svr->buff[j] = NULL; }
                if (svr->pbuf[j]) { free(svr->pbuf[j]); svr->pbuf[j] = NULL; }
            }
            sprintf(errmsg,"rtk server malloc error");
            return 0;
        }
    }
    
    /*初始化闪烁计算器*/
    /* 先释放之前可能分配的内存 */
    if (svr->scint_calc) {
        free_scintillation_calculator((scintillation_calculator_t*)svr->scint_calc);
        free(svr->scint_calc);
        svr->scint_calc = NULL;
    }
    
    svr->scint_calc = malloc(sizeof(scintillation_calculator_t));
    if (!svr->scint_calc) {
        // 清理所有已分配的缓冲区
        for (int j = 0; j < 3; j++) {
            if (svr->buff[j]) { free(svr->buff[j]); svr->buff[j] = NULL; }
            if (svr->pbuf[j]) { free(svr->pbuf[j]); svr->pbuf[j] = NULL; }
        }
        for (int j = 0; j < 2; j++) {
            if (svr->sbuf[j]) { free(svr->sbuf[j]); svr->sbuf[j] = NULL; }
        }
        sprintf(errmsg,"scintillation calculator malloc error");
        return 0;
    }
    
    if (init_scintillation_calculator((scintillation_calculator_t*)svr->scint_calc,ismopt) != 0) {
        free(svr->scint_calc);
        svr->scint_calc = NULL;
        // 清理所有已分配的缓冲区
        for (int j = 0; j < 3; j++) {
            if (svr->buff[j]) { free(svr->buff[j]); svr->buff[j] = NULL; }
            if (svr->pbuf[j]) { free(svr->pbuf[j]); svr->pbuf[j] = NULL; }
        }
        for (int j = 0; j < 2; j++) {
            if (svr->sbuf[j]) { free(svr->sbuf[j]); svr->sbuf[j] = NULL; }
        }
        sprintf(errmsg,"scintillation calculator init failed");
        tracet(1,"rtksvrstart: scintillation calculator init failed\n");
        return 0;
    } else {
        scintillation_calculator_t *scint_calc = (scintillation_calculator_t*)svr->scint_calc;
        if (svr->ismopt.ismlog && svr->ismopt.calculate) ismopen(svr->ismopt.ismfile);
        if (svr->ismopt.teclog && svr->ismopt.calculate) tecopen(svr->ismopt.tecfile);
    }

    if (svr->ismopt.corrmeaslog) corropen(svr->ismopt.corrmeasfile);
    if (svr->ismopt.phasemeaslog) phaseopen(svr->ismopt.phasemeasfile);
    if (svr->ismopt.tecmeaslog) tecobsopen(svr->ismopt.tecmeasfile);

    if(!load_enable_sys_freq(&svr->ismopt))     trace(2, "rtksvrstart: load enable system failed.\n");
    if(!load_satexclude(&svr->ismopt))          trace(2, "rtksvrstart: load enable system failed.\n");
    if(!load_tec_freq_table(&svr->ismopt))      trace(2, "rtksvrstart: load tec freq failed.\n");
    if(!load_glofcn(svr->ismopt.glonassfcn))    trace(2, "rtksvrstart: load glonass fcn failed.\n");
    if(!load_dcb_table(&svr->ismopt))           trace(2, "rtksvrstart: load rcv dcb failed.\n");

    elmask = svr->ismopt.elmask;
    snrmask = svr->ismopt.snrmask;

    /* set solution options */
    for (i=0;i<2;i++) {
        svr->solopt[i]=solopt[i];
    }
    /* set base station position */
    if (prcopt->refpos!=POSOPT_SINGLE) {
        for (i=0;i<6;i++) {
            svr->rtk.rb[i]=i<3?prcopt->rb[i]:0.0;
        }
    }
    /* update navigation data */
    for (i=0;i<MAXSAT*4 ;i++) svr->nav.eph [i].ttr=time0;
    for (i=0;i<NSATGLO*2;i++) svr->nav.geph[i].tof=time0;
    for (i=0;i<NSATSBS*2;i++) svr->nav.seph[i].tof=time0;
    
    /* set monitor stream */
    svr->moni=moni;
    
    /* open input streams */
    for (i=0;i<8;i++) {
        rw=i<3?STR_MODE_R:STR_MODE_W;
        if (strs[i]!=STR_FILE) rw|=STR_MODE_W;
        if (!stropen(svr->stream+i,strs[i],rw,paths[i])) {
            sprintf(errmsg,"str%d open error path=%s",i+1,paths[i]);
            for (i--;i>=0;i--) strclose(svr->stream+i);
            
            /* 清理闪烁计算器 */
            if (svr->scint_calc) {
                free_scintillation_calculator((scintillation_calculator_t*)svr->scint_calc);
                free(svr->scint_calc);
                svr->scint_calc = NULL;
            }
            if (svr->scint_log_file) {
                fclose(svr->scint_log_file);
                svr->scint_log_file = NULL;
            }
            /* 释放已分配的输入/输出缓冲区，避免启动失败时内存泄漏 */
            for (int k = 0; k < 3; k++) {
                if (svr->buff[k]) { free(svr->buff[k]); svr->buff[k] = NULL; }
                if (svr->pbuf[k]) { free(svr->pbuf[k]); svr->pbuf[k] = NULL; }
            }
            for (int k = 0; k < 2; k++) {
                if (svr->sbuf[k]) { free(svr->sbuf[k]); svr->sbuf[k] = NULL; }
            }
            return 0;
        }
        /* set initial time for rtcm and raw */
        if (i<3) {
            time=utc2gpst(timeget());
            svr->raw [i].time=strs[i]==STR_FILE?strgettime(svr->stream+i):time;
            svr->rtcm[i].time=strs[i]==STR_FILE?strgettime(svr->stream+i):time;
        }
    }
    /* sync input streams */
    strsync(svr->stream,svr->stream+1);
    strsync(svr->stream,svr->stream+2);
    
    /* write start commands to input streams */
    for (i=0;i<3;i++) {
        if (!cmds[i]) continue;
        strwrite(svr->stream+i,(unsigned char *)"",0); /* for connect */
        sleepms(100);
        strsendcmd(svr->stream+i,cmds[i]);
    }
    /* write solution header to solution streams */
    for (i=3;i<5;i++) {
        writesolhead(svr->stream+i,svr->solopt+i-3);
    }
    
    /* create rtk server thread */
#ifdef WIN32
    if (!(svr->thread=CreateThread(NULL,0,rtksvrthread,svr,0,NULL))) {
#else
    if (pthread_create(&svr->thread,NULL,rtksvrthread,svr)) {
#endif
        for (i=0;i<MAXSTRRTK;i++) strclose(svr->stream+i);
        
        /* 清理闪烁计算器 */
        if (svr->scint_calc) {
            free_scintillation_calculator((scintillation_calculator_t*)svr->scint_calc);
            free(svr->scint_calc);
            svr->scint_calc = NULL;
        }
        if (svr->scint_log_file) {
            fclose(svr->scint_log_file);
            svr->scint_log_file = NULL;
        }
        /* 释放已分配的输入/输出缓冲区，避免线程创建失败时内存泄漏 */
        for (int k = 0; k < 3; k++) {
            if (svr->buff[k]) { free(svr->buff[k]); svr->buff[k] = NULL; }
            if (svr->pbuf[k]) { free(svr->pbuf[k]); svr->pbuf[k] = NULL; }
        }
        for (int k = 0; k < 2; k++) {
            if (svr->sbuf[k]) { free(svr->sbuf[k]); svr->sbuf[k] = NULL; }
        }
        
        sprintf(errmsg,"thread create error\n");
        return 0;
    }
    
    /* 启动成功提示 */
    tracet(2, "RTK服务器启动成功\n");
    if (svr->scint_calc) {
        tracet(2, "电离层闪烁监测功能已启用\n");
    }
    
    return 1;
}

/* stop rtk server -------------------------------------------------------------
* start rtk server thread
* args   : rtksvr_t *svr    IO rtk server
*          char    **cmds   I  input stream stop commands
*                              cmds[0]=input stream rover (NULL: no command)
*                              cmds[1]=input stream base  (NULL: no command)
*                              cmds[2]=input stream ephem (NULL: no command)
* return : none
*-----------------------------------------------------------------------------*/
extern void rtksvrstop(rtksvr_t *svr, char **cmds) 
{
    int i;
    tracet(3,"rtksvrstop:\n");
    
    /* write stop commands to input streams */
    rtksvrlock(svr);
    for (i=0;i<3;i++) {
        if (cmds[i]) strsendcmd(svr->stream+i,cmds[i]);
    }
    rtksvrunlock(svr);
    
    /* stop rtk server */
    svr->state=0;
    
    /* free rtk server thread */
#ifdef WIN32
    WaitForSingleObject(svr->thread,10000);
    CloseHandle(svr->thread);
#else
    pthread_join(svr->thread,NULL);
#endif
    
    /* *** 清理闪烁计算器资源 *** */
    if (svr->scint_calc) {
        /* 最后一次输出闪烁数据 */
        if (svr->scint_log_file) {
            // calculate_scint_param_freq(svr->scint_calc);
            // output_scintillation_record(svr->scint_calc, svr->scint_log_file);
            fprintf(svr->scint_log_file, "# 监测结束\n");
            fflush(svr->scint_log_file);
        }
        
        free_scintillation_calculator((scintillation_calculator_t*)svr->scint_calc);
        free(svr->scint_calc);
        svr->scint_calc = NULL;
        
        tracet(2, "闪烁计算器已清理\n");
    }
    
    /* 关闭闪烁日志文件 */
    if (svr->scint_log_file) {
        fclose(svr->scint_log_file);
        svr->scint_log_file = NULL;
        tracet(2, "闪烁日志文件已关闭\n");
    }
}
/* open output/log stream ------------------------------------------------------
* open output/log stream
* args   : rtksvr_t *svr    IO rtk server
*          int     index    I  output/log stream index
*                              (3:solution 1,4:solution 2,5:log rover,
*                               6:log base station,7:log correction)
*          int     str      I  output/log stream types (STR_???)
*          char    *path    I  output/log stream path
*          solopt_t *solopt I  solution options
* return : status (1:ok 0:error)
*-----------------------------------------------------------------------------*/
extern int rtksvropenstr(rtksvr_t *svr, int index, int str, const char *path,
                         const solopt_t *solopt)
{
    tracet(3,"rtksvropenstr: index=%d str=%d path=%s\n",index,str,path);
    
    if (index<3||index>7||!svr->state) return 0;
    
    rtksvrlock(svr);
    
    if (svr->stream[index].state>0) {
        rtksvrunlock(svr);
        return 0;
    }
    if (!stropen(svr->stream+index,str,STR_MODE_W,path)) {
        tracet(2,"stream open error: index=%d\n",index);
        rtksvrunlock(svr);
        return 0;
    }
    if (index<=4) {
        svr->solopt[index-3]=*solopt;
        
        /* write solution header to solution stream */
        writesolhead(svr->stream+index,svr->solopt+index-3);
    }
    rtksvrunlock(svr);
    return 1;
}
/* close output/log stream -----------------------------------------------------
* close output/log stream
* args   : rtksvr_t *svr    IO rtk server
*          int     index    I  output/log stream index
*                              (3:solution 1,4:solution 2,5:log rover,
*                               6:log base station,7:log correction)
* return : none
*-----------------------------------------------------------------------------*/
extern void rtksvrclosestr(rtksvr_t *svr, int index)
{
    tracet(3,"rtksvrclosestr: index=%d\n",index);
    
    if (index<3||index>7||!svr->state) return;
    
    rtksvrlock(svr);
    
    strclose(svr->stream+index);
    
    rtksvrunlock(svr);
}
/* get observation data status -------------------------------------------------
* get current observation data status
* args   : rtksvr_t *svr    I  rtk server
*          int     rcv      I  receiver (0:rover,1:base,2:ephem)
*          gtime_t *time    O  time of observation data
*          int     *sat     O  satellite prn numbers
*          double  *az      O  satellite azimuth angles (rad)
*          double  *el      O  satellite elevation angles (rad)
*          int     **snr    O  satellite snr for each freq (dBHz)
*                              snr[i][j] = sat i freq j snr
*          int     *vsat    O  valid satellite flag
* return : number of satellites
*-----------------------------------------------------------------------------*/
extern int rtksvrostat(rtksvr_t *svr, int rcv, gtime_t *time, int *sat,
                       double *az, double *el, int **snr, int *vsat)
{
    int i,j,ns;
    
    tracet(4,"rtksvrostat: rcv=%d\n",rcv);
    
    if (!svr->state) return 0;
    rtksvrlock(svr);
    ns=svr->obs[rcv][0].n;
    if (ns>0) {
        *time=svr->obs[rcv][0].data[0].time;
    }
    for (i=0;i<ns;i++) {
        sat [i]=svr->obs[rcv][0].data[i].sat;
        az  [i]=svr->rtk.ssat[sat[i]-1].azel[0];
        el  [i]=svr->rtk.ssat[sat[i]-1].azel[1];
        for (j=0;j<NFREQ;j++) {
            snr[i][j]=(int)(svr->obs[rcv][0].data[i].SNR[j]*SNR_UNIT+0.5);
        }
        if (svr->rtk.sol.stat==SOLQ_NONE||svr->rtk.sol.stat==SOLQ_SINGLE) {
            vsat[i]=svr->rtk.ssat[sat[i]-1].vs;
        }
        else {
            vsat[i]=svr->rtk.ssat[sat[i]-1].vsat[0];
        }
    }
    rtksvrunlock(svr);
    return ns;
}
/* get stream status -----------------------------------------------------------
* get current stream status
* args   : rtksvr_t *svr    I  rtk server
*          int     *sstat   O  status of streams
*          char    *msg     O  status messages
* return : none
*-----------------------------------------------------------------------------*/
extern void rtksvrsstat(rtksvr_t *svr, int *sstat, char *msg)
{
    int i;
    char s[MAXSTRMSG],*p=msg;
    
    tracet(4,"rtksvrsstat:\n");
    
    rtksvrlock(svr);
    for (i=0;i<MAXSTRRTK;i++) {
        sstat[i]=strstat(svr->stream+i,s);
        if (*s) p+=sprintf(p,"(%d) %s ",i+1,s);
    }
    rtksvrunlock(svr);
}
/* mark current position -------------------------------------------------------
* open output/log stream
* args   : rtksvr_t *svr    IO rtk server
*          char    *name    I  marker name
*          char    *comment I  comment string
* return : status (1:ok 0:error)
*-----------------------------------------------------------------------------*/
extern int rtksvrmark(rtksvr_t *svr, const char *name, const char *comment)
{
    char buff[MAXSOLMSG+1],tstr[32],*p,*q;
    double tow,pos[3];
    int i,sum,week;
    
    tracet(4,"rtksvrmark:name=%s comment=%s\n",name,comment);
    
    if (!svr->state) return 0;
    
    rtksvrlock(svr);
    
    time2str(svr->rtk.sol.time,tstr,3);
    tow=time2gpst(svr->rtk.sol.time,&week);
    ecef2pos(svr->rtk.sol.rr,pos);
    
    for (i=0;i<2;i++) {
        p=buff;
        if (svr->solopt[i].posf==SOLF_STAT) {
            p+=sprintf(p,"$MARK,%d,%.3f,%d,%.4f,%.4f,%.4f,%s,%s\r\n",week,tow,
                       svr->rtk.sol.stat,svr->rtk.sol.rr[0],svr->rtk.sol.rr[1],
                       svr->rtk.sol.rr[2],name,comment);
        }
        else if (svr->solopt[i].posf==SOLF_NMEA) {
            p+=sprintf(p,"$GPTXT,01,01,02,MARK:%s,%s,%.9f,%.9f,%.4f,%d,%s",
                       name,tstr,pos[0]*R2D,pos[1]*R2D,pos[2],svr->rtk.sol.stat,
                       comment);
            for (q=(char *)buff+1,sum=0;*q;q++) sum^=*q; /* check-sum */
            p+=sprintf(p,"*%02X\r\n",sum);
        }
        else {
            p+=sprintf(p,"%s MARK: %s,%s,%.9f,%.9f,%.4f,%d,%s\r\n",COMMENTH,
                       name,tstr,pos[0]*R2D,pos[1]*R2D,pos[2],svr->rtk.sol.stat,
                       comment);
        }
        strwrite(svr->stream+i+3,(uint8_t *)buff,(int)(p-buff));
        saveoutbuf(svr,(uint8_t *)buff,(int)(p-buff),i);
    }
    if (svr->moni) {
        p=buff;
        p+=sprintf(p,"%s MARK: %s,%s,%.9f,%.9f,%.4f,%d,%s\r\n",COMMENTH,
                   name,tstr,pos[0]*R2D,pos[1]*R2D,pos[2],svr->rtk.sol.stat,
                   comment);
        strwrite(svr->moni,(uint8_t *)buff,(int)(p-buff));
    }
    rtksvrunlock(svr);
    return 1;
}