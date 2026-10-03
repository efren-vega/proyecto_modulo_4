


with

    
    stg_hpd_worklog as (select * from EDW_DEV_EVB.raw_bmc_helix.hpd_worklog ), 
    stg_hpd_help_desk as (select * from EDW_DEV_EVB.raw_bmc_helix.hpd_help_desk ), 
    ttc_s_org_ext as (select * from EDW_DEV_EVB.raw_siebel_telco.s_org_ext ),
    cm_to_alarm_issue as (select * from EDW_DEV_EVB.raw_servassure_nxt.cm_to_alarm_issue ),
    ttc_dim_clientes as (select * from EDW_DEV_EVB.bm.ttc_dim_clientes ), 
    ttc_dim_equipos as (select * from EDW_DEV_EVB.bm.ttc_dim_equipos ), 


    

    dim_clientes_filtro as 
    (
    select widmt_cliente, widdim_cliente, scd_fecha_inicio, scd_fecha_fin, widdim_region
    from ttc_dim_clientes 
    where widmt_cliente != '632667547E7CD3E0466547863E1207A8C0C0C549'
    and cliente != '1'
    and scd_fecha_inicio <= current_date()-1
    and scd_fecha_fin >= current_date() -1
    ),

    dim_equipos_filtro as 
    (
    select
        widmt_cliente,
        widdim_equipo,
        row_id,
        mac,
        mac_2,
        chip_id,
        no_serie,
        tipo_tecnologia,
        scd_fecha_inicio,
        scd_fecha_fin
    FROM ttc_dim_equipos
    where orig_id = 3
    and flg_eliminado = 0
    and widmt_cliente != '632667547E7CD3E0466547863E1207A8C0C0C549'  
    and scd_fecha_inicio <= current_date()-1
    and scd_fecha_fin >= current_date() -1
    ),

    dim_equipos_posibles_macs AS 
    (
    select distinct
        widmt_cliente,
        widdim_equipo,
        mac,
        no_serie,
        row_id,
        tipo_tecnologia,
        upper(trim(mac_match)) mac_match,
        scd_fecha_inicio,
        scd_fecha_fin
    FROM (
        select
            widmt_cliente,
            widdim_equipo,
            mac,
            no_serie,
            row_id,
            tipo_tecnologia,
            mac mac_match,
            scd_fecha_inicio,
            scd_fecha_fin
        from dim_equipos_filtro where mac is not null
            union all
        select
            widmt_cliente,
            widdim_equipo,
            mac,
            no_serie,
            row_id,
            tipo_tecnologia,
            mac_2 mac_match,
            scd_fecha_inicio,
            scd_fecha_fin
        from dim_equipos_filtro where mac_2 is not null
            union all
        select
            widmt_cliente,
            widdim_equipo,
            mac,
            no_serie,
            row_id,
            tipo_tecnologia,
            chip_id mac_match,
            scd_fecha_inicio,
            scd_fecha_fin
        from dim_equipos_filtro where chip_id is not null
            union all
        select
            widmt_cliente,
            widdim_equipo,
            mac,
            no_serie,
            row_id,
            tipo_tecnologia,
            no_serie mac_match,
            scd_fecha_inicio,
            scd_fecha_fin
        from dim_equipos_filtro where no_serie is not null
        )
    ),
    
    univ_mt_incidenciashelix_hdp as
    (
        SELECT 
        hdp.incident_number incidencia,
        to_timestamp(hdp.submit_date) fecha_incidencia,
        hdp.detailed_decription
        from stg_hpd_help_desk hdp
        where 1=1
        and submitter in ('EAssure', 'Netcool')
        and detailed_decription like '%CmMacAddress%'
        and (
            to_timestamp(hdp.submit_date) >= current_date() -1
            and to_timestamp(hdp.submit_date) < dateadd(day, 1, current_date()-1)
            )
    ),

    univ_mt_incidenciashelix_worklog as
    (
    select 
        hdp.incident_number incidencia,
        to_timestamp(hdp.submit_date) fecha_incidencia,
        worklog.detailed_description,
    from  stg_hpd_help_desk hdp
    inner join stg_hpd_worklog worklog on hdp.incident_number = worklog.incident_number
    where 1=1
    and hdp.submitter in ('EAssure', 'Netcool')
    and worklog.detailed_description like '%*Affected Subscribers*%'
    and worklog.detailed_description like '%CmMacAddress%'
    and (
            (
            to_timestamp(hdp.submit_date) >= current_date() -1
            and to_timestamp(hdp.submit_date) < dateadd(day, 1, current_date()-1)
            )
            or
            (
            to_timestamp(worklog.submit_date) >= current_date() -1
            and to_timestamp(worklog.submit_date) < dateadd(day, 1, current_date()-1)
            )
        )
    ),
    univ_mt_incidencias_helix_netcool_notadetallada as 
    (
        SELECT 
            hdp.incident_number incidencia,
            to_timestamp(hdp.submit_date) fecha_incidencia,
            hdp.notadetallada
        from stg_hpd_help_desk hdp
        where 1=1
        and submitter = 'Netcool' -- EAssure  ya no envía CmMacAddress en notadetallada
        and notadetallada like '%CmMacAddress%' 
        and (
            to_timestamp(hdp.submit_date) >= current_date() -1
            and to_timestamp(hdp.submit_date) < dateadd(day, 1, current_date()-1)
            )
    ),

    univ_mt_incidencias_helix_eassure as 
    (
        SELECT 
            hdp.incident_number incidencia,
            to_timestamp(hdp.submit_date) fecha_incidencia,
            hdp.detailed_decription
        from stg_hpd_help_desk hdp
        where 1=1
        and submitter = 'EAssure' -- Incidencias que HDP no le reporta a Worklog
        and notadetallada like '%Affected%' 
        and (
            to_timestamp(hdp.submit_date) >= current_date() -1
            and to_timestamp(hdp.submit_date) < dateadd(day, 1, current_date()-1)
            )
    ),
    

    
    parsed_modems_worklog AS 
    (
    SELECT 
        h.incidencia,
        h.fecha_incidencia,
        case WHEN  REGEXP_LIKE(f.value, '^[A-Z0-9]{12}.*') THEN SUBSTR(f.value, 1, 12) ELSE NULL END as MAC
    FROM univ_mt_incidenciashelix_worklog h,
    LATERAL FLATTEN(input => SPLIT(REPLACE(h.detailed_description, '\r', '\n'), '\n')) f
    where 1=1
    and trim(f.value) != ''
    and mac is not null
    and mac not like '%CmMacAddress%'
    group by all
    ),
    
    parsed_modems_hdp_notadetallada AS 
    (
    SELECT 
        h.incidencia,
        h.fecha_incidencia,
        case WHEN  REGEXP_LIKE(f.value, '^[A-Z0-9]{12}.*') THEN SUBSTR(f.value, 1, 12) ELSE NULL END as MAC
    FROM univ_mt_incidencias_helix_netcool_notadetallada h,
    LATERAL FLATTEN(input => SPLIT(REPLACE(h.notadetallada, '\r', '\n'), '\n')) f
    where 1=1
    and trim(f.value) != ''
    and mac is not null
    and mac not like '%CmMacAddress%'
    group by all
    ),

    parsed_modems_hdp AS 
    (
    SELECT 
        h.incidencia,
        h.fecha_incidencia,
        case WHEN  REGEXP_LIKE(f.value, '^[A-Z0-9]{12}.*') THEN SUBSTR(f.value, 1, 12) ELSE NULL END as MAC
    FROM univ_mt_incidenciashelix_hdp h,
    LATERAL FLATTEN(input => SPLIT(REPLACE(h.detailed_decription, '\r', '\n'), '\n')) f
    where 1=1
    and trim(f.value) != ''
    and mac is not null
    and mac not like '%CmMacAddress%'
    group by all
    ),
    
    parsed_modems_hdp_eassure AS 
    (
    SELECT 
        h.incidencia,
        h.fecha_incidencia,
        cmtai.cm_mac
    FROM univ_mt_incidencias_helix_eassure h
    inner join cm_to_alarm_issue cmtai
    on REGEXP_SUBSTR(h.DETAILED_DECRIPTION, 'Alarm ID:\\s*([\\w-]+)', 1, 1, 'e') = cmtai.alarm_id
    where 1=1
    group by all
    ),

    parsed_modems as (
        select * from parsed_modems_worklog 
        union 
        select * from parsed_modems_hdp 
        union 
        select * from parsed_modems_hdp_notadetallada
        union
        select * from parsed_modems_hdp_eassure
    ),
    
    -- 

    final as 
    ( 
    select
        de.widmt_cliente,
        upper(sha1(3 || nvl(pm.incidencia, '1'))) widmt_incidencia_remedy,
        de.widdim_equipo,
        dc.widdim_cliente,
        dc.widdim_region,
        upper(sha1(nvl( pm.incidencia || de.row_id, '31'))) widmt_incidencia_remedy_cliente,
        pm.fecha_incidencia,
        pm.incidencia incidencia,
        soe.name cliente,
        de.mac,
        de.no_serie num_serie,
        de.tipo_tecnologia
    FROM parsed_modems pm
    INNER JOIN dim_equipos_posibles_macs de
    ON pm.mac = de.mac_match
    INNER JOIN dim_clientes_filtro dc
    ON de.widmt_cliente = dc.widmt_cliente
    inner join ttc_s_org_ext soe on upper(sha1( 3 || nvl(soe.row_id,'1'))) = de.widmt_cliente
    where 1=1
    and pm.fecha_incidencia between dc.scd_fecha_inicio and dc.scd_fecha_fin
    and pm.fecha_incidencia between de.scd_fecha_inicio and de.scd_fecha_fin
    group by all
    )

    select * from final