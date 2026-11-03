from chao2.backend import display_blocks,PACKAGE

def test_separate_game_displays_do_not_share_focus():
    text=f'''Display: mDisplayId=0 rootTasks=1
    mFocusedApp=ActivityRecord{{u0 app.lawnchair/.Home}}
  Display: mDisplayId=3 rootTasks=1
    mCurrentFocus=Window{{u0 com.hypergryph.arknights/.Game}}
  Display: mDisplayId=4 rootTasks=1
    mFocusedApp=ActivityRecord{{u0 {PACKAGE}/.AppActivity}}'''
    blocks=dict(display_blocks(text))
    assert set(blocks)=={0,3,4}
    assert PACKAGE not in blocks[3]
    assert PACKAGE in blocks[4]
