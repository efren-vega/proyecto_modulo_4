


with

    
    stg_hpd_help_desk as (select * from EDW_DEV_EVB.raw_bmc_helix.hpd_help_desk ), 
    ttc_s_order_max as (select * from EDW_DEV_EVB.raw_siebel_telco.s_order ), 
    ttc_s_order_1 as (select * from EDW_DEV_EVB.raw_siebel_telco.s_order ),
--  tmp 2
    ttc_s_srv_req_max as (select * from EDW_DEV_EVB.raw_siebel_telco.s_srv_req ),
    ttc_s_srv_req_1 as (select * from EDW_DEV_EVB.raw_siebel_telco.s_srv_req ),
-- tmp 3 
    dim_incidencias_remedy_urgenci as (select * from EDW_DEV_EVB.raw_siebel_telco.s_srv_req ),
    ttc_s_evt_act_1 as (select * from EDW_DEV_EVB.raw_siebel_telco.s_evt_act ),
    ttc_s_org_ext_1 as (select * from EDW_DEV_EVB.raw_siebel_telco.s_org_ext ),
    remedy_hpd_help_desk_2 as (select * from EDW_DEV_EVB.raw_bmc_helix.hpd_help_desk ), 
--    unv_inc_rem as (select * from stg_bm.ttc_tmp_unv_mt_incidencias_remedy_telco_v),
    ttc_dim_incidencias_remedy as (select * from EDW_DEV_EVB.bm.ttc_dim_incidencias_remedy ),
    ttc_dim_region_remedy as (select * from EDW_DEV_EVB.bm.ttc_dim_region_remedy ), 
    ttc_dim_fallas_1 as (select * from EDW_DEV_EVB.bm.ttc_dim_fallas ), 




    
    univ_mt_incidenciashelix as
    (
        select INCIDENT_NUMBER ROW_ID 
        from  stg_hpd_help_desk
        where incident_number is not null
        and (
              (submit_date  between
                  datediff('seconds', '1970-01-01 00:00:00'::timestamp_ntz, to_timestamp(to_char((trunc(current_date() -1, 'day')), 'DD/MM/YYYY'), 'DD/MM/YYYY'))
               and datediff('seconds', '1970-01-01 00:00:00'::timestamp_ntz, to_timestamp(to_char((trunc(current_date()-1, 'day')+2), 'DD/MM/YYYY'), 'DD/MM/YYYY'))
              )
              or(last_modified_date  between
                  datediff('seconds', '1970-01-01 00:00:00'::timestamp_ntz, to_timestamp(to_char((trunc(current_date() -1, 'day')), 'DD/MM/YYYY'), 'DD/MM/YYYY'))
               and datediff('seconds', '1970-01-01 00:00:00'::timestamp_ntz, to_timestamp(to_char((trunc(current_date()-1, 'day')+2), 'DD/MM/YYYY'), 'DD/MM/YYYY'))
              )
            )
    ),
    dim_incidencias_remedy_estat_1 as ( 
        select  
        dim_incidencias_remedy_estatus.clave as clave , 
        dim_incidencias_remedy_estatus.catalogo as catalogo , 
        dim_incidencias_remedy_estatus.descripcion as descripcion    
        from  
        ttc_dim_incidencias_remedy dim_incidencias_remedy_estatus   
        where 
        (dim_incidencias_remedy_estatus.catalogo = 'ESTATUS' )  
        
    ),
    dim_incidencias_remedy_impac_1 as( 
        select  
        dim_incidencias_remedy_impacto.orig_id as orig_id , 
        dim_incidencias_remedy_impacto.clave as clave , 
        dim_incidencias_remedy_impacto.catalogo as catalogo , 
        dim_incidencias_remedy_impacto.descripcion as descripcion    
        from  
        ttc_dim_incidencias_remedy dim_incidencias_remedy_impacto   
        where 
        (dim_incidencias_remedy_impacto.catalogo = 'IMPACTO')  
    ),   
    dim_incidencias_remedy_prior_1 as ( 
        select  
        dim_incidencias_remedy_priorid.clave as clave , 
        dim_incidencias_remedy_priorid.catalogo as catalogo , 
        dim_incidencias_remedy_priorid.descripcion as descripcion    
        from  
        ttc_dim_incidencias_remedy dim_incidencias_remedy_priorid   
        where 
        (dim_incidencias_remedy_priorid.catalogo= 'PRIORIDAD')
    ),
    dim_incidencias_remedy_urgen_1 as ( 
        select  
        dim_incidencias_remedy_urgenci.clave as clave , 
        dim_incidencias_remedy_urgenci.catalogo as catalogo , 
        dim_incidencias_remedy_urgenci.descripcion as descripcion    
        from  
        ttc_dim_incidencias_remedy dim_incidencias_remedy_urgenci   
        where 
        (dim_incidencias_remedy_urgenci.catalogo = 'URGENCIA')  
    ),
                    
    
    stg_mt_incidencias_remedy_tmp_1 as
    (   select   
            ttc_s_order_1.row_id  as row_id, 
            ttc_s_order_1.order_num as order_num 
        from  ( 
                select  
                max(ttc_s_order_max.row_id) as row_id , 
                ttc_s_order_max.order_num as order_num    
                from  stg_hpd_help_desk remedy_hpd_help_desk_1  
                inner join  ttc_s_order_max   
                    on  ttc_s_order_max.order_num = remedy_hpd_help_desk_1.n_mero_de_orden 
                where 
                (remedy_hpd_help_desk_1.incident_number in (select unv_inc_rem.row_id  
                                                    from univ_mt_incidenciashelix unv_inc_rem 
                                                    where 1=1) 
                )  
                group by 
                ttc_s_order_max.order_num  
          ) inline_view  
            inner join  ttc_s_order_1   on  inline_view.row_id = ttc_s_order_1.row_id 
        and inline_view.order_num = ttc_s_order_1.order_num 
        where (1=1)
    ),   

    stg_mt_incidencias_remedy_tmp_2 as(
    select   
        ttc_s_srv_req_1.row_id  as row_id, 
        ttc_s_srv_req_1.sr_num  as sr_num 
        from  ( 
        select  
          max(ttc_s_srv_req_max.row_id) as row_id , 
          ttc_s_srv_req_max.sr_num as sr_num    
        from  ttc_s_srv_req_max  
          inner join stg_hpd_help_desk remedy_hpd_help_desk1   
            on  ttc_s_srv_req_max.sr_num = remedy_hpd_help_desk1.caso_de_negocio 
        where 
          (remedy_hpd_help_desk1.incident_number in (select unv_inc_rem.row_id  
                                              from univ_mt_incidenciashelix unv_inc_rem 
                                              where 1=1) 
        )  
        group by 
          ttc_s_srv_req_max.sr_num  
          ) inline_view  inner join  ttc_s_srv_req_1   
            on  inline_view.row_id = ttc_s_srv_req_1.row_id 
        and inline_view.sr_num = ttc_s_srv_req_1.sr_num 
        where (1=1)
    ),

    stg_mt_incidencias_remedy_tmp_3 as(
      select  
         /*+parallel (6)*/ 
            sysdate() dw_fecha_creacion, 
            sysdate() dw_fecha_actualizacion, 
            upper(sha1(3 || nvl(join2_a.row_id, '1'))) widmt_caso_negocio, 
            upper(sha1(3 || nvl(ttc_s_org_ext_1.row_id, '1'))) widmt_cliente, 
            upper(sha1(3 || nvl(join3_a.row_id, '1'))) widmt_orden, 
            upper(sha1(3 || nvl(ttc_s_evt_act_1.row_id, '1'))) widmt_actividad, 
            ttc_dim_region_remedy.widdim_region_remedy, 
            nvl(ttc_dim_fallas_1.widdim_fallas, '1') widdim_fallas, 
            upper(sha1(3 || nvl(remedy_hpd_help_desk.original_incident_number, '1'))) widmt_incidencia_remedy_padre, 
            upper(sha1(3 || nvl(remedy_hpd_help_desk.incident_number, '1'))) widmt_incidencia_remedy, 
            dim_incidencias_remedy_impac_1.orig_id, 
            remedy_hpd_help_desk.incident_number incidencia, 
            nvl(remedy_hpd_help_desk.original_incident_number, '1') incidencia_padre, 
            remedy_hpd_help_desk.submitter remitente_id, 
            remedy_hpd_help_desk.last_name || ' ' || remedy_hpd_help_desk.first_name remitente_nombre, 
            remedy_hpd_help_desk.internet_e_mail remitente_mail,
            convert_timezone('Etc/GMT','America/Mexico_City', to_timestamp(remedy_hpd_help_desk.submit_date)) fecha_envio, 
            convert_timezone('Etc/GMT','America/Mexico_City', to_timestamp(remedy_hpd_help_desk.last_modified_date)) fecha_actualizacion, 
            convert_timezone('Etc/GMT','America/Mexico_City', to_timestamp(remedy_hpd_help_desk.reported_date)) fecha_notificacion,
            convert_timezone('Etc/GMT','America/Mexico_City', to_timestamp(remedy_hpd_help_desk.responded_date)) fecha_respuesta,
            convert_timezone('Etc/GMT','America/Mexico_City', to_timestamp(remedy_hpd_help_desk.fecha_de_reasignacion)) fecha_reasignacion, 
            convert_timezone('Etc/GMT','America/Mexico_City', to_timestamp(remedy_hpd_help_desk.fecha_de_primer_reasignacion_)) fecha_1er_reasignacion, 
            convert_timezone('Etc/GMT','America/Mexico_City', to_timestamp(remedy_hpd_help_desk.last_resolved_date)) fecha_ultima_resolucion,
            convert_timezone('Etc/GMT','America/Mexico_City', to_timestamp(remedy_hpd_help_desk.closed_date)) fecha_cierre,
            remedy_hpd_help_desk.assignee_login_id usuario_asignado,  
            remedy_hpd_help_desk.assigned_group grupo_asignado, 
            remedy_hpd_help_desk.last_modified_by ultima_modificacion_por, 
            remedy_hpd_help_desk.site ubicacion_cliente,
            nvl(dim_incidencias_remedy_estat_1.descripcion, to_char(remedy_hpd_help_desk.status)) estado, 
            remedy_hpd_help_desk.status_reason motivo_estado, 
            nvl(dim_incidencias_remedy_impac_1.descripcion, to_char(remedy_hpd_help_desk.impact)) impacto, 
            nvl(dim_incidencias_remedy_urgen_1.descripcion, to_char(remedy_hpd_help_desk.urgency)) urgencia, 
            nvl(dim_incidencias_remedy_prior_1.descripcion,to_char(remedy_hpd_help_desk.priority)) prioridad, 
            remedy_hpd_help_desk.escalated_ escalado, 
            remedy_hpd_help_desk.product_categorization_tier_1 nivel1, 
            remedy_hpd_help_desk.product_categorization_tier_2 nivel2, 
            remedy_hpd_help_desk.product_categorization_tier_3 nivel3, 
            remedy_hpd_help_desk.closure_product_category_tier1 cat_op_res_n1, 
            remedy_hpd_help_desk.closure_product_category_tier2 cat_op_res_n2, 
            remedy_hpd_help_desk.resolution_category_tier_3 cat_op_res_n3, 
            remedy_hpd_help_desk.description resumen, 
            remedy_hpd_help_desk.tipo_de_servicio tipo_servicio, 
            nvl(remedy_hpd_help_desk.servicio_afectado,'SIN INFORMACION') servicio_afectado,
            nvl(remedy_hpd_help_desk.no__de_cablemodems_afectados,0) cm_afectados, 
            nvl(remedy_hpd_help_desk.no__de_emtas_offline,0) emta_afectados, 
            nvl(remedy_hpd_help_desk.subscriptores_de_tv_afectados,0) stb_afectados, 
            remedy_hpd_help_desk.red tipo_red, 
            remedy_hpd_help_desk.tipo_de_reporte tipo_reporte, 
            remedy_hpd_help_desk.ubicacion_del_corte_o_falla ubicacion_corte, 
            remedy_hpd_help_desk.tecnico_que_resuelve tecnico_resuelve, 
            remedy_hpd_help_desk.tipo_de_reparacion tipo_reparacion, 
            remedy_hpd_help_desk.status_de_reparacion estatus_reparacion, 
            remedy_hpd_help_desk.tipo_de_falla_reportada tipo_falla, 
            remedy_hpd_help_desk.motivo_de_la_falla motivo_falla, 
            remedy_hpd_help_desk.solucion solucion_falla, 
            remedy_hpd_help_desk.closure_source origen_cierre, 
            remedy_hpd_help_desk.assigned_support_organization organizacion_cierre, 
            remedy_hpd_help_desk.company empresa, 
            remedy_hpd_help_desk.department departamento, 
            remedy_hpd_help_desk.organization organizacion, 
            remedy_hpd_help_desk.individual_transfers transferencias_individuos, 
            remedy_hpd_help_desk.group_transfers transferencias_grupos, 
            remedy_hpd_help_desk.sistema___zona_afectada hub_id, 
            ttc_s_org_ext_1.region region, 
            remedy_hpd_help_desk.assigned_support_company empresa_grupo_asignado, 
            remedy_hpd_help_desk.cuenta_siebel siebel_cuenta, 
            remedy_hpd_help_desk.n_mero_de_orden siebel_os, 
            remedy_hpd_help_desk.caso_de_negocio siebel_cn, 
            remedy_hpd_help_desk.comentarios comentarios, 
            remedy_hpd_help_desk.incident_association_type tipo_relacion, 
            remedy_hpd_help_desk.resolution resolucion, 
            remedy_hpd_help_desk.detailed_decription notas, 
            remedy_hpd_help_desk.postmortemrequiere postmortem_requiere, 
            remedy_hpd_help_desk.postmortemsecuenta postmortem_se_cuenta, 
            convert_timezone('Etc/GMT','America/Mexico_City', to_timestamp(remedy_hpd_help_desk.postmortemfecha)) postmortem_fecha,
            remedy_hpd_help_desk.assignee usuario_asignado_nombre, 
            remedy_hpd_help_desk.site_group2 grupo_localidades, 
            remedy_hpd_help_desk.vendor_ticket_number no_ticket_proveedor, 
            remedy_hpd_help_desk.vendor_group grupo_proveedores, 
            -- ***
            -- esta repetida se comenta, validar que no afecte
            ----------------          
            remedy_hpd_help_desk.sistema___zona_afectada ciudad_hub_afectado, 
            remedy_hpd_help_desk.porcentajedegradacion porcentaje_degradacion, 
            remedy_hpd_help_desk.nodo nodo_interno, 
            case when (
            to_char(convert_timezone('Etc/GMT','America/Mexico_City', to_timestamp(remedy_hpd_help_desk.submit_date) ), 'HH24')  
                        in (7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22)  
                        or to_char(convert_timezone('Etc/GMT','America/Mexico_City', to_timestamp(remedy_hpd_help_desk.last_resolved_date) ), 'HH24') 
                        in (7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22))    
                then 'Y'  
                else 'N' end flg_primetime,
            remedy_hpd_help_desk.status_reason2, 
            remedy_hpd_help_desk.entry_id, 
            remedy_hpd_help_desk.fecha_asignacion_tecnico, 
            remedy_hpd_help_desk.funcionalidadcustompadrehijo_,
            remedy_hpd_help_desk.loginidtras,
            remedy_hpd_help_desk.nivafectcableaccess,
            remedy_hpd_help_desk.origenticketnext,
            remedy_hpd_help_desk.primer_grupo_asignado,
            remedy_hpd_help_desk.resolution_category,
            remedy_hpd_help_desk.resolution_category_tier_2,
            remedy_hpd_help_desk.serviceci,
            remedy_hpd_help_desk.status_ppl,
            remedy_hpd_help_desk.support_group_role,
            remedy_hpd_help_desk.tecnologia,
            remedy_hpd_help_desk.tipociudad,
            remedy_hpd_help_desk.tipoticketintegracion,
            remedy_hpd_help_desk.upstream1,
            remedy_hpd_help_desk.valida_cuenta,
            remedy_hpd_help_desk.vendor_assignee_groups,
            remedy_hpd_help_desk.vendor_assignee_groups_parent,
            remedy_hpd_help_desk.vendor_assignment_status,
            remedy_hpd_help_desk.vip,
            remedy_hpd_help_desk.sla_hold,
            remedy_hpd_help_desk.sla_res_business_hour_seconds,
            remedy_hpd_help_desk.sla_responded,
            remedy_hpd_help_desk.slm_priority,
            remedy_hpd_help_desk.slm_status,
            remedy_hpd_help_desk.time_zone,
            remedy_hpd_help_desk.unknownuser,
            remedy_hpd_help_desk.falla_en_,
            remedy_hpd_help_desk.falla_en_2,
            remedy_hpd_help_desk.no__de_cablemodems_afectados_a,
            remedy_hpd_help_desk.no__de_emtas_offline_aux,
            remedy_hpd_help_desk.no__serie_de_equipo_instalado,
            remedy_hpd_help_desk.no_de_acometidas,
            remedy_hpd_help_desk.postmortemadjunto,
            remedy_hpd_help_desk.postmortemautomatico,
            remedy_hpd_help_desk.pre_incident_number_redapunto,
            remedy_hpd_help_desk.previousstatus,
            remedy_hpd_help_desk.priority_weight
  from  ((( dim_incidencias_remedy_urgen_1  
    right outer join  (((((ttc_s_evt_act_1  
        right outer join  (ttc_s_org_ext_1  
            right outer join  ( 
                select  
                remedy_hpd_help_desk_2.submitter as submitter , 
                remedy_hpd_help_desk_2.submit_date as submit_date , 
                remedy_hpd_help_desk_2.assignee_login_id as assignee_login_id , 
                remedy_hpd_help_desk_2.last_modified_by as last_modified_by , 
                remedy_hpd_help_desk_2.last_modified_date as last_modified_date , 
                remedy_hpd_help_desk_2.status as status , 
                remedy_hpd_help_desk_2.caso_de_negocio as caso_de_negocio , 
                remedy_hpd_help_desk_2.site_group2 as site_group2 , 
                remedy_hpd_help_desk_2.postmortemrequiere as postmortemrequiere , 
                remedy_hpd_help_desk_2.postmortemfecha as postmortemfecha , 
                remedy_hpd_help_desk_2.postmortemsecuenta as postmortemsecuenta , 
                remedy_hpd_help_desk_2.porcentajedegradacion as porcentajedegradacion , 
                remedy_hpd_help_desk_2.resolution as resolution , 
                remedy_hpd_help_desk_2.status_reason as status_reason , 
                remedy_hpd_help_desk_2.detailed_decription as detailed_decription , 
                remedy_hpd_help_desk_2.urgency as urgency , 
                remedy_hpd_help_desk_2.impact as impact , 
                remedy_hpd_help_desk_2.tipo_de_servicio as tipo_de_servicio , 
                remedy_hpd_help_desk_2.incident_number as incident_number , 
                remedy_hpd_help_desk_2.priority as priority , 
                remedy_hpd_help_desk_2.assignee as assignee , 
                remedy_hpd_help_desk_2.assigned_group as assigned_group , 
                remedy_hpd_help_desk_2.servicio_afectado as servicio_afectado , 
                remedy_hpd_help_desk_2.sistema___zona_afectada as sistema___zona_afectada , 
                remedy_hpd_help_desk_2.no__de_cablemodems_afectados as no__de_cablemodems_afectados , 
                remedy_hpd_help_desk_2.cuenta_siebel as cuenta_siebel , 
                remedy_hpd_help_desk_2.comentarios as comentarios , 
                remedy_hpd_help_desk_2.assigned_support_company as assigned_support_company , 
                remedy_hpd_help_desk_2.nodo as nodo , 
                remedy_hpd_help_desk_2.fecha_de_reasignacion as fecha_de_reasignacion , 
                remedy_hpd_help_desk_2.fecha_de_primer_reasignacion_ as fecha_de_primer_reasignacion_ , 
                remedy_hpd_help_desk_2.n_mero_de_orden as n_mero_de_orden , 
                remedy_hpd_help_desk_2.no__de_emtas_offline as no__de_emtas_offline , 
                remedy_hpd_help_desk_2.subscriptores_de_tv_afectados as subscriptores_de_tv_afectados , 
                remedy_hpd_help_desk_2.last_name as last_name , 
                remedy_hpd_help_desk_2.first_name as first_name , 
                remedy_hpd_help_desk_2.organization as organization , 
                remedy_hpd_help_desk_2.assigned_support_organization as assigned_support_organization , 
                remedy_hpd_help_desk_2.description as description , 
                remedy_hpd_help_desk_2.company as company , 
                remedy_hpd_help_desk_2.tecnico_que_resuelve as tecnico_que_resuelve , 
                remedy_hpd_help_desk_2.ubicacion_del_corte_o_falla as ubicacion_del_corte_o_falla , 
                remedy_hpd_help_desk_2.red as red , 
                remedy_hpd_help_desk_2.tipo_de_reporte as tipo_de_reporte , 
                remedy_hpd_help_desk_2.internet_e_mail as internet_e_mail , 
                remedy_hpd_help_desk_2.tipo_de_reparacion as tipo_de_reparacion , 
                remedy_hpd_help_desk_2.status_de_reparacion as status_de_reparacion , 
                remedy_hpd_help_desk_2.tipo_de_falla_reportada as tipo_de_falla_reportada , 
                remedy_hpd_help_desk_2.motivo_de_la_falla as motivo_de_la_falla , 
                remedy_hpd_help_desk_2.solucion as solucion , 
                remedy_hpd_help_desk_2.closure_source as closure_source , 
                remedy_hpd_help_desk_2.resolution_category_tier_3 as resolution_category_tier_3 , 
                remedy_hpd_help_desk_2.closure_product_category_tier1 as closure_product_category_tier1 , 
                remedy_hpd_help_desk_2.closure_product_category_tier2 as closure_product_category_tier2 , 
                remedy_hpd_help_desk_2.group_transfers as group_transfers , 
                remedy_hpd_help_desk_2.individual_transfers as individual_transfers , 
                remedy_hpd_help_desk_2.vendor_group as vendor_group , 
                remedy_hpd_help_desk_2.site as site , 
                remedy_hpd_help_desk_2.original_incident_number as original_incident_number , 
                remedy_hpd_help_desk_2.incident_association_type as incident_association_type , 
                remedy_hpd_help_desk_2.vendor_ticket_number as vendor_ticket_number , 
                remedy_hpd_help_desk_2.last_resolved_date as last_resolved_date , 
                remedy_hpd_help_desk_2.reported_date as reported_date , 
                remedy_hpd_help_desk_2.responded_date as responded_date , 
                remedy_hpd_help_desk_2.closed_date as closed_date , 
                remedy_hpd_help_desk_2.product_categorization_tier_1 as product_categorization_tier_1 , 
                remedy_hpd_help_desk_2.department as department , 
                remedy_hpd_help_desk_2.product_categorization_tier_3 as product_categorization_tier_3 , 
                remedy_hpd_help_desk_2.product_categorization_tier_2 as product_categorization_tier_2 , 
                remedy_hpd_help_desk_2.escalated_ as escalated_,
                remedy_hpd_help_desk_2.status_reason2, 
                remedy_hpd_help_desk_2.entry_id, 
                remedy_hpd_help_desk_2.fecha_asignacion_tecnico, 
                remedy_hpd_help_desk_2.funcionalidadcustompadrehijo_,
                remedy_hpd_help_desk_2.loginidtras,
                remedy_hpd_help_desk_2.nivafectcableaccess,
                remedy_hpd_help_desk_2.origenticketnext,
                remedy_hpd_help_desk_2.primer_grupo_asignado,
                remedy_hpd_help_desk_2.resolution_category,
                remedy_hpd_help_desk_2.resolution_category_tier_2,
                remedy_hpd_help_desk_2.serviceci,
                remedy_hpd_help_desk_2.status_ppl,
                remedy_hpd_help_desk_2.support_group_role,
                remedy_hpd_help_desk_2.tecnologia,
                remedy_hpd_help_desk_2.tipociudad,
                remedy_hpd_help_desk_2.tipoticketintegracion,
                remedy_hpd_help_desk_2.upstream1,
                remedy_hpd_help_desk_2.valida_cuenta,
                remedy_hpd_help_desk_2.vendor_assignee_groups,
                remedy_hpd_help_desk_2.vendor_assignee_groups_parent,
                remedy_hpd_help_desk_2.vendor_assignment_status,
                remedy_hpd_help_desk_2.vip,
                remedy_hpd_help_desk_2.sla_hold,
                remedy_hpd_help_desk_2.sla_res_business_hour_seconds,
                remedy_hpd_help_desk_2.sla_responded,
                remedy_hpd_help_desk_2.slm_priority,
                remedy_hpd_help_desk_2.slm_status,
                remedy_hpd_help_desk_2.time_zone,
                remedy_hpd_help_desk_2.unknownuser,
                remedy_hpd_help_desk_2.falla_en_,
                remedy_hpd_help_desk_2.falla_en_2,
                remedy_hpd_help_desk_2.no__de_cablemodems_afectados_a,
                remedy_hpd_help_desk_2.no__de_emtas_offline_aux,
                remedy_hpd_help_desk_2.no__serie_de_equipo_instalado,
                remedy_hpd_help_desk_2.no_de_acometidas,
                remedy_hpd_help_desk_2.postmortemadjunto,
                remedy_hpd_help_desk_2.postmortemautomatico,
                remedy_hpd_help_desk_2.pre_incident_number_redapunto,
                remedy_hpd_help_desk_2.previousstatus,
                remedy_hpd_help_desk_2.priority_weight
                from  
                remedy_hpd_help_desk_2   
                where 
                (remedy_hpd_help_desk_2.incident_number  
                                                    in (select unv_inc_rem.row_id  
                                                    from univ_mt_incidenciashelix unv_inc_rem 
                                                    where 1=1) 
                )  
            ) remedy_hpd_help_desk   
        on  ttc_s_org_ext_1.name = remedy_hpd_help_desk.cuenta_siebel 
        )   
        on  ttc_s_evt_act_1.activity_uid = remedy_hpd_help_desk.vendor_ticket_number
        )  left outer join  stg_mt_incidencias_remedy_tmp_1 join3_a   
        on  join3_a.order_num = remedy_hpd_help_desk.n_mero_de_orden 
        )  left outer join  stg_mt_incidencias_remedy_tmp_2 join2_a     
        on  join2_a.sr_num = remedy_hpd_help_desk.caso_de_negocio 
        )  left outer join  dim_incidencias_remedy_estat_1   
        on  nvl(remedy_hpd_help_desk.status,-1) = dim_incidencias_remedy_estat_1.clave 
        )  left outer join  dim_incidencias_remedy_impac_1   
        on  nvl(remedy_hpd_help_desk.impact,-1) = dim_incidencias_remedy_impac_1.clave 
        )   
        on  nvl(remedy_hpd_help_desk.urgency,-1) = dim_incidencias_remedy_urgen_1.clave 
        )  left outer join dim_incidencias_remedy_prior_1   
        on  nvl(remedy_hpd_help_desk.priority,-1) = dim_incidencias_remedy_prior_1.clave 
        )  left outer join   ttc_dim_region_remedy   
        on  case  
            when upper(remedy_hpd_help_desk.sistema___zona_afectada) in ('MTY N/A', 
                                                                        'MTY/NA')  
            then 'MONTERREY'                
        else 
        rtrim(ltrim(translate(regexp_replace(regexp_replace(upper(remedy_hpd_help_desk.sistema___zona_afectada),'[^[:alpha:]]|(HUB)',' '),'[ ]{2,}',' '),'ÁÉÍÓÚ','AEIOU')))  
        end = ttc_dim_region_remedy.hub_remedy 
        )  left outer join  ttc_dim_fallas_1   
        on  remedy_hpd_help_desk.assigned_group = ttc_dim_fallas_1.grupo_asignado 
        and  substr(remedy_hpd_help_desk.solucion, 1, 4000) = ttc_dim_fallas_1.solucion_falla 
  where  
          (1=1)
    ),
    
    
    final as (select * from stg_mt_incidencias_remedy_tmp_3)

select *
from final