import decimal, json, math, requests
from datetime import datetime
from urllib.parse import urlencode

from .settings import API_KEY, BUSINESS_UNIT_REVIEWS_API_URL, FIND_BUSINESS_UNIT_API_URL


class TrustPilot:
    def __init__(self, domain):
        self.domain = domain
        self.business_unit = self._get_business_unit()

    def get_trustscore(self, limit=300):
        """
        This method will calculate and return the trustscore 
        of this instance's domain based on the latest x reviews,
        where x is determined by the limit parameter.
        """
        # define the starting url and query string
        # for retrieving reviews.
        query_string = urlencode({
            'perPage': 100,
        })

        url = BUSINESS_UNIT_REVIEWS_API_URL % { 
            'business_unit' : self.business_unit,
            'query_string' : query_string
        }

        # get the datetime now as a benchmark for evaluating
        # age of reviews
        now = datetime.now()

        # initialise starting variables
        scores_list = []
        max_scores_list = []
        review_count = 0

        review_count_reached = False
        has_next = True
        
        # loop until the end of the reviews or until the
        # limit has been reached.
        while (not review_count_reached) and has_next:
            # get the data from the api
            data = self._get_json(url)

            # loop through each review in the results
            for review in data['reviews']:
                # only process reviews that count towards score
                if review['countsTowardsTrustScore']:
                    # calculate score for review
                    score, max_score = self._score_review(
                        stars = review['stars'], 
                        created_at = review['createdAt'],
                        now = now,
                    )

                    # append to relevant lists
                    scores_list.append(score)
                    max_scores_list.append(max_score)

                    # increment review counter
                    review_count += 1

                    # have we hit the review limit?
                    if review_count >= limit:
                        # don't process any more reviews
                        review_count_reached = True
                        break

            # check to make sure there is another page
            has_next = False
            for link in data['links']:
                if link['rel'] == 'next-page':
                    has_next = True
                    url = link['href']


        # calculate the trustscore
        trustscore = self._calculate_trustscore(scores_list=scores_list, 
            max_scores_list=max_scores_list)

        # round the score and ensure python rounds up .5
        context = decimal.getcontext()
        context.rounding = decimal.ROUND_HALF_UP
        return round(trustscore, 1) 

    def _get_json(self, url):
        """
        Adds the API key as a header makes a
        GET request to the url parameter and 
        returns the JSON.
        """
        headers = {'apikey': API_KEY }
        response = requests.get(url, headers=headers)
        return response.json()

    def _get_business_unit(self):
        """
        Returns the business unit for this
        instance's domain.
        """
        url = FIND_BUSINESS_UNIT_API_URL % { 'domain' : self.domain }
        data = self._get_json(url)
        return data['id']

    def _score_review(self, stars, created_at, now):
        """
        Returns a score between 1 and 0 for the review
        and the max score possible based on the date of
        the review, as the weighting decreases over time.
        """
        total_score = self._score_stars(stars=stars)

        # get the date score so that aging can be applied
        # this is also the maximum possible score
        date_score = max_score = self._score_date(datetime_str=created_at, now=now)

        # apply aging and return
        aged_score = total_score * date_score
        return aged_score, max_score

    def _score_stars(self, stars):
        """
        There are five possible star ratings, that are evenly 
        spaced out. 1 star will return a score of 0 and each 
        extra star will increase by 0.25, so that 5 returns 
        a score of 1.
        """
        stars_score = (stars - 1) * 0.25
        return stars_score

    def _score_date(self, datetime_str, now):
        """
        Using a logistic function sigmoid curve, returns
        a value between 0 and 1 for the date parameter
        relative to the now parameter. 

        Dates closer to now will have a value closer to
        1. Dates further in the past will have a value
        closer to 0.

        L = the curve's maximum value
        k = the steepness of the curve
        x0 = the x-value of the sigmoid's midpoint
        """
        # set logistic variables
        # setting x0 to 6 months means a score has
        # half it's value after 6 months.
        L = 1
        k = 0.004
        x0 = 365 * 0.5

        # convert string date to datetime object and calc age in days
        datetime_obj = datetime.strptime(datetime_str, '%Y-%m-%dT%H:%M:%SZ')
        age_days = (now - datetime_obj).days
            
        # calculate the logistic funciton value
        logistic_value = L / (1 + math.exp(-k * (age_days - x0)))

        # transform so that new dates are closer to 1 and return
        logistic_value = -logistic_value + 1    
        return logistic_value

    def _calculate_trustscore(self, scores_list, max_scores_list):
        """
        Calculate the trustscore.
        
        Thi is achieved by working out the avarage score, 
        and performs a quality check against the min and max
        thresholds, which are dependend on the number of reviews.

        This prevents a company that has only a small number
        of reviews having a really high or low score.
        """
        # calculate the trustscore and scale to Trust Pilot's scale
        trustscore = sum(scores_list) / sum(max_scores_list) * 10
        trustscore = self._check_score_threshold(trustscore, len(scores_list))
        return trustscore

    def _check_score_threshold(self, score, number_of_reviews):
        """
        The quality check to make sure the score is within the thresholds
        """
        min_score = self._min_score_threshold(number_of_reviews=number_of_reviews)
        max_score = self._max_score_threshold(number_of_reviews=number_of_reviews)

        if min_score <= score <= max_score:
            return score
        elif score < min_score:
            return min_score
        else:
            return max_score

    def _max_score_threshold(self, number_of_reviews):
        """
        Calculate the maximum score possible based on the number
        of reviews. The threshold is determined by a log function.
        """
        # should start at 6, so need to calculate the y translation
        starting_score = 6
        x_translation = 0
        y_translation = starting_score - math.log(x_translation + 1)

        max_score = math.log(number_of_reviews + x_translation) + y_translation
        return max_score

    def _min_score_threshold(self, number_of_reviews):
        """
        Calculate the minimum score possible based on the number
        of reviews. The threshold is determined by a log function.
        """
        # should start at 6, so need to calculate the y translation
        starting_score = 6
        x_translation = 5
        base = 1.5
        y_translation = starting_score - (math.log(x_translation + 1, base) * -1)

        min_score = math.log(number_of_reviews + x_translation, base) * -1 + y_translation
        return min_score
