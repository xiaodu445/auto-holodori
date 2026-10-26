"""Import human-cropped game templates and their optional text sidecars."""
import json
from hashlib import sha256
from pathlib import Path
import re
from .template_library import TemplateLibrary


def import_game_templates(root,domain,source=None):
    if not re.fullmatch(r'[a-z][a-z0-9_-]*',domain or ''): raise ValueError('Invalid domain')
    root=Path(root)
    source=Path(source) if source else root/'domains'/domain/'data'/'template_sources'/'in_game'
    if not source.is_dir(): raise ValueError('Template source directory does not exist')
    library=TemplateLibrary(root/'domains'/domain/'vision_library')
    knowledge=root/'domains'/domain/'knowledge'/'templates'
    output={'imported':[],'updated':[],'skipped':[],'errors':[]}
    records=library.records()
    for image in sorted(source.rglob('*')):
        if image.suffix.lower() not in ('.png','.jpg','.jpeg','.bmp') or not image.is_file(): continue
        try:
            metadata_path=image.with_suffix('.json')
            metadata=json.loads(metadata_path.read_text(encoding='utf-8-sig')) if metadata_path.exists() else {}
            if not isinstance(metadata,dict): raise ValueError('Sidecar JSON must be an object')
            if metadata.keys()-{'name','role','threshold','notes','environments','mask_mode'}: raise ValueError('Unknown sidecar fields')
            name=metadata.get('name',image.stem)
            if not isinstance(name,str) or not re.fullmatch(r'[a-z][a-z0-9_]*',name): raise ValueError('Use lowercase English snake_case filename, or set name in JSON')
            group=image.relative_to(source).parts[0]
            role=metadata.get('role',{'buttons':'button','icons':'icon','states':'panel'}.get(group,'object'))
            threshold=metadata.get('threshold',.9)
            mask_mode=metadata.get('mask_mode','none')
            if mask_mode not in ('none','warm_ui'): raise ValueError('Invalid mask_mode')
            notes=metadata.get('notes','')
            environments=metadata.get('environments',[domain])
            if role not in ('button','icon','panel','object'): raise ValueError('Invalid role')
            if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not 0<threshold<=1: raise ValueError('Invalid threshold')
            if not isinstance(notes,str) or len(notes)>4000: raise ValueError('notes must contain at most 4000 characters')
            if not isinstance(environments,list) or not environments or any(not isinstance(v,str) or not v for v in environments): raise ValueError('environments must be a list of strings')
            digest=sha256(image.read_bytes()).hexdigest()
            document=knowledge/f'{name}.md'
            reference=str(document.relative_to(root))
            text_path=image.with_suffix('.md')
            text=text_path.read_text(encoding='utf-8-sig') if text_path.exists() else ''
            expected_document=f'# {name}\n\n- 来源：用户提供的裁剪图片\n- 角色：{role}\n- 图像相似度阈值：{threshold}\n- 验证：模板命中不等于动作成功；匹配后检查当前状态。\n\n{notes}\n\n{text}\n'
            existing=next((r for r in records if r.name==name and r.image_sha256==digest),None)
            fields={'mask_mode':mask_mode,'notes':notes,'role':role,'threshold':threshold,'environments':environments,'knowledge_file':reference}
            if existing and all(getattr(existing,k)==v for k,v in fields.items()) and document.exists() and (not text or document.read_text(encoding='utf-8-sig')==expected_document):
                output['skipped'].append(name); continue
            if existing:
                for key,value in fields.items(): setattr(existing,key,value)
                library._save(records)
                output['updated'].append(name)
            else:
                existing=library.add(name,image,environments,threshold,notes,role,reference)
                existing.mask_mode=mask_mode
                records=[r for r in library.records() if r.name!=name or r.id==existing.id]
                for r in records:
                    if r.id==existing.id: r.mask_mode=mask_mode
                library._save(records)
                output['imported'].append(name)
            knowledge.mkdir(parents=True,exist_ok=True)
            # Preserve existing hand-edited knowledge unless an explicit source Markdown is provided.
            if text or not document.exists():
                document.write_text(expected_document,encoding='utf-8')
        except (ValueError,OSError,TypeError) as error:
            output['errors'].append({'file':str(image.relative_to(source)),'message':str(error)})
    return output
