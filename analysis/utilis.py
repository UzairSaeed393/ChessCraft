def get_move_classification(prev_eval, current_eval, is_white):
    """
    Calculates the quality of a move based on the change in evaluation.
    """
    # Adjust difference based on whose turn it was
    diff = (current_eval - prev_eval) if is_white else (prev_eval - current_eval)
    
    if diff < -2.0:
        return "Blunder", "?? This move loses significant material or position."
    elif diff < -1.0:
        return "Mistake", "? A significant error that hands over the advantage."
    elif diff < -0.5:
        return "Inaccuracy", "?! Not the best, but not a total disaster."
    elif diff > 0.4:
        # A move is 'Brilliant' if it improves the eval significantly 
        # (usually involves a sacrifice, but we'll start simple)
        return "Brilliant", "!! An incredible find that secures the advantage!"
    else:
        return "Best", "The engine agrees this was the top choice."