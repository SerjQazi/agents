# Pappu Inventory Migration Testing Checklist

## Phase 1: Basic Functionality
- [ ] **Open/Close**: Press 'TAB' to open and close the inventory.
- [ ] **Movement**: Drag an item from one slot to another.
- [ ] **Hotbar**: Drag an item to slots 1-5 and use keybinds 1-5.
- [ ] **Hotbar Toggle**: Press 'Z' to see the hotbar overlay.
- [ ] **Use Item**: Right-click or drag to "Use" for a consumable (e.g., water).
- [ ] **Drop Item**: Drag an item out of the inventory to drop it.
- [ ] **Pick Up**: Walk over a drop and open inventory or use 'E'/'Target' to pick up.

## Phase 2: Containers & Shops
- [ ] **Stashes**: Open a standard stash (e.g., apartment or job stash).
- [ ] **Trunks**: Open a vehicle trunk.
- [ ] **Gloveboxes**: Open a vehicle glovebox.
- [ ] **Shops**: Open a shop (24/7 or Ammunation) and buy an item.
- [ ] **Player Robbing**: Verify "Rob" functionality on another player.

## Phase 3: Weapons & Attachments
- [ ] **Equip Weapon**: Move a weapon to a hotbar slot and use it.
- [ ] **Ammo Use**: Verify ammo decreases when shooting.
- [ ] **Attachments**: Apply an attachment (scope/suppressor) to a weapon via the weapon panel.
- [ ] **Durability**: Check if weapon quality decreases after use.

## Phase 4: Advanced Systems
- [ ] **Item Decay**: Give yourself a food item with a decay rate and check quality over time.
- [ ] **Crafting**: Access a crafting station and craft a simple item.
- [ ] **Metadata**: Verify ID Cards show the correct player name/info.
- [ ] **MDT Integration**: Check if a weapon serial is correctly logged/searchable in MDT (if ps-mdt is used).

## Phase 5: Compatibility & Safety
- [ ] **SQL Check**: Verify items persist across relogs.
- [ ] **Console Errors**: Check F8 (Client) and Server console for script errors.
- [ ] **Weight Limits**: Try to exceed max weight and confirm `AddItem` fails.
