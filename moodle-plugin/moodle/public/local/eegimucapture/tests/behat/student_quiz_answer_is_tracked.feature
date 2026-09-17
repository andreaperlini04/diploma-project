@local_eegimucapture @click_tracker @javascript
Feature: The click tracker records answers during a quiz attempt
  In order to analyse how students answer questions during a quiz
  As a researcher
  I need each interaction with a question to produce the correct semantic
    event type, carrying the right question number

  Background:
    Given the following "courses" exist:
      | fullname | shortname | format |
      | Tracker Quiz Course | testtrackerquiz | topics |
    And the following "users" exist:
      | username | firstname | lastname | email |
      | student1 | Student | One | student1@example.com |
    And the following "course enrolments" exist:
      | user | course | role |
      | student1 | testtrackerquiz | student |
    # Created through the generator: the interface path goes through the
    # activity chooser and the question bank, which change between releases.
    And the following "activities" exist:
      | activity | name | intro | course | idnumber |
      | quiz | Tracker Quiz | Test quiz | testtrackerquiz | quiztracker |
    And the following "question categories" exist:
      | contextlevel | reference | name |
      | Activity module | quiztracker | Test questions |
    And the following "questions" exist:
      | questioncategory | qtype | name | questiontext |
      | Test questions | truefalse | Tracker Question | Tracker Question |
    # Covers the two models truefalse cannot: two_of_four has single=0, hence
    # independent checkboxes; ddwtos needs detection by comparison on mouseup.
    And the following "questions" exist:
      | questioncategory | qtype | name | template |
      | Test questions | multichoice | Multiple Answer Question | two_of_four |
      | Test questions | ddwtos | Drag Question | fox |
    # All on the same page: this avoids navigation steps between attempt
    # pages and fixes the question numbers to 1, 2 and 3.
    And quiz "Tracker Quiz" contains the following questions:
      | question | page |
      | Tracker Question | 1 |
      | Multiple Answer Question | 1 |
      | Drag Question | 1 |
    And I log in as "student1"
    And I am on the "Tracker Quiz" "mod_quiz > View" page
    And I press "Attempt quiz"
    # The start confirmation appears as a modal dialogue: without this step
    # the browser stays on the quiz view page and no question is available.
    And I click on "Start attempt" "button"

  Scenario: Selecting an answer produces answer_selected
    When I click on "True" "radio" in the "Tracker Question" "question"
    Then the eegimucapture client should have sent an event of type "answer_selected" with payload "question_number" "1"

  Scenario: Changing an existing answer produces answer_changed, not another answer_selected
    Given I click on "True" "radio" in the "Tracker Question" "question"
    And the eegimucapture client should have sent an event of type "answer_selected" with payload "question_number" "1"
    When I click on "False" "radio" in the "Tracker Question" "question"
    Then the eegimucapture client should have sent an event of type "answer_changed" with payload "question_number" "1"

  # Deselection tells the toggle model from the replacement one: under
  # replacement a second click on the same value produces no event.
  # Multichoice checkboxes have no label element (aria-labelledby), so Mink's
  # "checkbox" selector cannot find them: the answer-text selector is used.
  Scenario: Deselecting a checkbox produces answer_cleared
    Given I click on "One" "qtype_multichoice > Answer" in the "Which are the odd numbers?" "question"
    And the eegimucapture client should have sent an event of type "answer_selected" with payload "question_number" "2"
    When I click on "One" "qtype_multichoice > Answer" in the "Which are the odd numbers?" "question"
    Then the eegimucapture client should have sent an event of type "answer_cleared" with payload "question_number" "2"

  # Moodle's drag and drop component emits no change event on the hidden state
  # inputs: the plugin compares their values on every mouse release.
  Scenario: Dragging a word into a space produces drag_drop_completed
    When I drag "quick" to space "1" in the drag and drop into text question
    Then the eegimucapture client should have sent an event of type "drag_drop_completed" with payload "question_number" "3"

  # Space 2 belongs to group 2, where choice numbering restarts from 1: checks
  # that item_text reports the word placed, not the same-numbered choice of
  # group 1, which precedes it in document order.
  Scenario: item_text reports the word from the correct group
    When I drag "fox" to space "2" in the drag and drop into text question
    Then the eegimucapture client should have sent an event of type "drag_drop_completed" with payload "item_text" "fox"
