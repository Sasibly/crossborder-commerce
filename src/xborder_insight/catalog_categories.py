"""Category metadata is separate from candidate and published SKU lifecycle."""
CATEGORIES=(
    {'id':'air_purifier','name':'Air purifiers','name_zh':'空气净化器'},
    {'id':'coffee_machine','name':'Coffee machines','name_zh':'半自动咖啡机'},
    {'id':'electric_kettle','name':'Electric kettles','name_zh':'电热水壶'},
    {'id':'pet_fountain','name':'Pet fountains','name_zh':'宠物饮水机'},
    {'id':'robot_vacuum','name':'Robot vacuums','name_zh':'扫地机器人'},
    {'id':'wireless_charger','name':'Wireless chargers','name_zh':'无线充电器'},
)
OTHER={'id':'other','name':'Other','name_zh':'其他'}


def from_source(source):
    identity=source.get('dataset')
    return next((dict(c) for c in CATEGORIES if c['id']==identity),dict(OTHER))


def product_category(product):
    return from_source(product.get('snapshot',{}).get('candidate',{}).get('source_json',{}))


def stages(candidates,products):
    rows={c['id']:dict(c,candidates=0,drafts=0,published=0,in_stock=0) for c in (*CATEGORIES,OTHER)}
    for candidate in candidates:rows[from_source(candidate['source_json'])['id']]['candidates']+=1
    for product in products:
        row=rows[product_category(product)['id']]
        if product['status']=='draft':row['drafts']+=1
        if product['status']=='published':
            row['published']+=1
            if product['stock']>0:row['in_stock']+=1
    return {'categories':[row for row in rows.values() if row['id']!='other' or row['candidates'] or row['drafts'] or row['published']],
            'visibility_rule':'Only published SKUs appear in the buyer store; category options are analysis metadata.'}
