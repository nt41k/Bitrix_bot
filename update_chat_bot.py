import sys

# Read chat_bot.py
with open(r'C:\Users\user322\Desktop\kwork-code\Bitrix bot\modules\chat_bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace find_row_in_google_sheets function
old_func = '''def find_row_in_google_sheets(consignment, sheet_name=None):
    """Find row number in Google Sheets by consignment.
    
    Returns relative rowNumber for Google Apps Script (1 = first data row).
    If sheet_name is provided, searches only that sheet.
    If sheet_name is None, searches all GOOGLE_SHEETS and returns first match.
    """
    try:
        sheets_to_search = [sheet_name] if sheet_name else GOOGLE_SHEETS
        
        for sheet in sheets_to_search:
            data = fetch_google_data(sheet)
            rows = data.get("data", [])
            if not rows:
                continue
            
            headers = rows[0]
            try:
                identifier_idx = headers.index("НОМЕР ТРАНСПОРТНОГО ДОКУМЕНТА (КОНОСАМЕНТ)")
            except ValueError:
                continue
            
            for row_idx, row in enumerate(rows[1:], start=1):
                if len(row) > identifier_idx and row[identifier_idx] == consignment:
                    return row_idx  # Relative: 1 = first data row
        
        return None
    except Exception:
        return None'''

new_func = '''def find_row_in_google_sheets(consignment, container=None, sheet_name=None):
    """Find row number in Google Sheets by consignment and optionally container.
    
    If container is provided, searches for exact match (consignment + container).
    If container is None, searches only by consignment (first match).
    
    Returns relative rowNumber for Google Apps Script (1 = first data row).
    If sheet_name is provided, searches only that sheet.
    If sheet_name is None, searches all GOOGLE_SHEETS and returns first match.
    """
    try:
        sheets_to_search = [sheet_name] if sheet_name else GOOGLE_SHEETS
        
        for sheet in sheets_to_search:
            data = fetch_google_data(sheet)
            rows = data.get("data", [])
            if not rows:
                continue
            
            headers = rows[0]
            try:
                identifier_idx = headers.index("НОМЕР ТРАНСПОРТНОГО ДОКУМЕНТА (КОНОСАМЕНТ)")
            except ValueError:
                continue
            
            # If container specified, find container column index
            container_idx = None
            if container:
                try:
                    container_idx = headers.index("НОМЕР ТРАНСПОРТНОГО СРЕДСТВА (КОНТЕЙНЕР)")
                except ValueError:
                    continue
            
            for row_idx, row in enumerate(rows[1:], start=1):
                if len(row) > identifier_idx and row[identifier_idx] == consignment:
                    if container and container_idx is not None:
                        # Need exact match: consignment + container
                        if len(row) > container_idx and row[container_idx] == container:
                            return row_idx  # Exact match found
                    else:
                        # Match by consignment only (first match)
                        return row_idx
        
        return None
    except Exception:
        return None'''

if old_func in content:
    content = content.replace(old_func, new_func)
    print('OK: find_row_in_google_sheets updated')
else:
    print('ERROR: Could not find old function')
    sys.exit(1)

# Replace writeback block
old_writeback = '''            # Writeback to Google Sheets for regular commands only
            if regular_commands:
                try:
                    row_number = find_row_in_google_sheets(consignment)
                    if row_number:
                        wb_changes = {}
                        for crm_field, value in regular_commands.items():
                            if crm_field.startswith("ufCrm_"):
                                uf_field = "UF_CRM_" + crm_field[6:]
                            else:
                                uf_field = crm_field
                            if uf_field in CRM_TO_GOOGLE:
                                g_col_name = CRM_TO_GOOGLE[uf_field]
                                wb_changes[g_col_name] = value
                        if wb_changes:
                            wb_result = writeback_to_google([{
                                "rowNumber": row_number,
                                "changes": wb_changes
                            }])
                            if wb_result.get("success"):
                                total_writebacks += 1
                            else:
                                writeback_errors += 1
                            print(f"[chat_bot] Writeback result: {wb_result}")
                except Exception as e:
                    writeback_errors += 1
                    print(f"[chat_bot] Writeback error (non-critical): {e}")'''

new_writeback = '''            # Writeback to Google Sheets for regular commands only
            if regular_commands:
                try:
                    # Use container-aware search if container is present
                    row_number = find_row_in_google_sheets(consignment, container)
                    if row_number:
                        wb_changes = {}
                        for crm_field, value in regular_commands.items():
                            if crm_field.startswith("ufCrm_"):
                                uf_field = "UF_CRM_" + crm_field[6:]
                            else:
                                uf_field = crm_field
                            if uf_field in CRM_TO_GOOGLE:
                                g_col_name = CRM_TO_GOOGLE[uf_field]
                                wb_changes[g_col_name] = value
                        if wb_changes:
                            # Use container-based writeback for exact row targeting
                            wb_result = writeback_to_google([{
                                "conosament": consignment,
                                "container": container,
                                "changes": wb_changes
                            }])
                            if wb_result.get("success"):
                                total_writebacks += 1
                            else:
                                writeback_errors += 1
                            print(f"[chat_bot] Writeback result: {wb_result}")
                except Exception as e:
                    writeback_errors += 1
                    print(f"[chat_bot] Writeback error (non-critical): {e}")'''

if old_writeback in content:
    content = content.replace(old_writeback, new_writeback)
    print('OK: Writeback block updated')
else:
    print('ERROR: Could not find old writeback block')
    sys.exit(1)

# Save file
with open(r'C:\Users\user322\Desktop\kwork-code\Bitrix bot\modules\chat_bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('OK: chat_bot.py saved successfully')
