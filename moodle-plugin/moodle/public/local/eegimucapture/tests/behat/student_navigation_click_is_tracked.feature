@local_eegimucapture @click_tracker @javascript
Feature: The click tracker records navigation clicks
  In order to analyse how students navigate through a course
  As a researcher
  I need a click on a link outside a question to produce a navigation_clicked event

  Background:
    Given the following "courses" exist:
      | fullname | shortname | format |
      | Tracker Test Course | testtracker | topics |
    And the following "users" exist:
      | username | firstname | lastname | email |
      | student1 | Student | One | student1@example.com |
    And the following "course enrolments" exist:
      | user | course | role |
      | student1 | testtracker | student |
    # Created through the generator: the activity chooser changes between
    # Moodle releases and made these scenarios fragile.
    And the following "activities" exist:
      | activity | name | intro | course | idnumber |
      | page | Tracker Test Page | Page content | testtracker | pagetracker |
    And I log in as "student1"
    And I am on "testtracker" course homepage

  Scenario: Clicking a navigation link produces navigation_clicked
    When I click on "Tracker Test Page" "link"
    Then the eegimucapture client should have sent an event of type "navigation_clicked" with payload "label" "Tracker Test Page"
